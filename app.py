from flask import Flask, render_template, request, jsonify, redirect, session, flash
from flask_cors import CORS
import os
import pymysql
from pymysql.cursors import DictCursor
from pymysql.err import IntegrityError
from pymysql.cursors import DictCursor



app = Flask(__name__)
app.secret_key = "secret-key"
CORS(app)

#connect to db
db = pymysql.connect(
    host="localhost", 
    user="mrocazap",
    password="newpassword",
    database="mrocazap", 
    cursorclass=DictCursor
)

#helper functions
def normalize_loc(city: str, state: str) -> str: #Normalize the format of user state and city
   
    if not city or not state:
        return ""

    # Capitalize city properly and make state uppercase
    city_clean = city.strip().title()
    state_clean = state.strip().upper()

    return f"{city_clean}, {state_clean}"

@app.route("/")
def home(): 
    return redirect("/login")

#User database

#TODO: need a signup.html

#create User if not already exists - signup
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        name     = request.form["name"].strip()
        email    = request.form["email"].strip().lower()
        city     = request.form["user_city"].strip().title()
        state    = request.form["user_state"].strip().upper()[:2]
        age      = int(request.form["user_age"])
        gender   = request.form["user_gender"].strip().upper()[:1]

        # Use DictCursor so fetchone() returns a dict
        cursor = db.cursor(DictCursor)

        # Pre-check for existing username OR email
        cursor.execute(
            "SELECT username, email FROM Users WHERE username = %s OR email = %s LIMIT 1",
            (username, email)
        )
        existing = cursor.fetchone()  # -> dict or None

        if existing:
            if existing.get("username") == username:
                flash("That username is already taken. Please pick another.", "error")
                return render_template("signup.html")
            if existing.get("email") == email:
                flash("That email is already registered. Try logging in.", "error")
                return render_template("signup.html")

        # Insert (still guarded for race conditions)
        try:
            cursor.execute(
                """
                INSERT INTO Users
                (username, email, full_name, user_password, user_city, user_state, user_age, user_gender)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (username, email, name, password, city, state, age, gender)
            )
            db.commit()
            flash("Account created! Please log in.", "success")
            return redirect("/login")

        except IntegrityError as e:
            db.rollback()
            # duplicate key (username PK or email UNIQUE)
            if "1062" in str(e):
                flash("This username or email is already in use.", "error")
            else:
                flash("Unexpected error creating the account. Please try again.", "error")
            return render_template("signup.html")

    # GET
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # DictCursor so we can access columns by name (user["user_password"])
        cursor = db.cursor(DictCursor)
        cursor.execute("SELECT * FROM Users WHERE username = %s LIMIT 1", (username,))
        user = cursor.fetchone()

        if user and user.get("user_password") == password:  # consider hashing later
            session["username"]   = user["username"]
            session["user_city"]  = user["user_city"]
            session["user_state"] = user["user_state"]
            return redirect("/events")

        # Bad creds: show alert + keep what they typed for username
        flash("Sorry, the username or password is incorrect.", "error")
        return render_template("login.html"), 401  # re-render same page

    # GET
    return render_template("login.html")


@app.route("/logout")
def logout(): 
    session.clear()
    return redirect("/login")        

#TODO: events.html, where each event is a button/card that then calls /select_event/<event_id>

#based on user location from session, find events in that location
from pymysql.cursors import DictCursor

@app.route("/events")
def find_events(): 
    if "username" not in session: 
        return redirect("/login")

    city = session["user_city"]
    state = session["user_state"]
    target_location = normalize_loc(city, state)

    cursor = db.cursor(DictCursor)  
    cursor.execute(
        "SELECT * FROM Single_Events WHERE venue_location = %s",
        (target_location,)
    )
    events = cursor.fetchall()
    
    return render_template("events.html", events=events)

@app.route("/api/events/<int:event_id>/swipe", methods=["POST"])
def swipe_event(event_id):
    if "username" not in session:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    choice = (data.get("choice") or "").lower()

    username = session["username"]
    cursor = db.cursor(DictCursor)

    # We’ll always return some JSON
    response = {
        "status": "ok",
        "choice": choice,
        "group_created": False,
        "group_id": None,
        "already_waiting": False,
    }

    rating_value = 1 if choice == "yes" else 0
    cursor.execute("""
        INSERT INTO User_Event_Ratings (username, event_id, rating)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE rating = VALUES(rating)
    """, (username, event_id, rating_value))
    db.commit()

    if choice == "yes":
        # 0) bump popularity for this event
        cursor.execute(
            """
            UPDATE Single_Events
               SET popularity = COALESCE(popularity, 0) + 1
             WHERE event_id = %s
            """,
            (event_id,),
        )

        # 0) If already signed up and wating, error
        cursor.execute("select 1 from Matches where username = %s and event_id = %s and group_id is null limit 1", (username, event_id))
        if cursor.fetchone() is not None:
            flash("Hang out tight, we're waiting to match you to a group!")
            return redirect("/events")

        # 1) record this user's match for the event
        cursor.execute(
            "INSERT INTO Matches (event_id, username) VALUES (%s, %s)",
            (event_id, username),
        )
        db.commit()

        # 2) how many matches are still ungrouped for this event?
        cursor.execute(
            "SELECT COUNT(*) AS count FROM Matches WHERE event_id = %s AND group_id IS NULL",
            (event_id,),
        )
        record = cursor.fetchone()
        count = record["count"] if record else 0

        # 3) if enough, create a group, then assign those matches to it
        # TODO: change threshold to 10 later or figure out how big the groups should be? 
        if count >= 2:
            # create the group
            cursor.execute(
                "INSERT INTO Match_Groups (event_id) VALUES (%s)",
                (event_id,),
            )
            db.commit()

            # IMPORTANT: get the group_id we just created
            group_id = cursor.lastrowid

            # assign all ungrouped matches for this event to this new group
            cursor.execute(
                """
                UPDATE Matches
                SET group_id = %s
                WHERE event_id = %s
                AND group_id IS NULL
                """,
                (group_id, event_id),
            )
            db.commit()
            return redirect(f"/group/{group_id}")

        db.commit()
        return jsonify(response)

    # For "no" (or anything else), we don't create a match
    return jsonify(response)


'''#create a match based on a selected event
@app.route("/select_event/<int:event_id>")
def event_selected(event_id):
    # must be logged in
    if "username" not in session:
        return redirect("/login")

    username = session["username"]
    cursor = db.cursor()

    # 0) If already signed up and wating, error
    cursor.execute("select 1 from Matches where username = %s and event_id = %s and group_id is null limit 1", (username, event_id))
    if cursor.fetchone() is not None:
        flash("Hang out tight, we're waiting to match you to a group!")
        return redirect("/events")

    # 1) record this user's match for the event
    cursor.execute(
        "INSERT INTO Matches (event_id, username) VALUES (%s, %s)",
        (event_id, username),
    )
    db.commit()

    # 2) how many matches are still ungrouped for this event?
    cursor.execute(
        "SELECT COUNT(*) AS count FROM Matches WHERE event_id = %s AND group_id IS NULL",
        (event_id,),
    )
    record = cursor.fetchone()
    count = record["count"] if record else 0

    # 3) if enough, create a group, then assign those matches to it
    # TODO: change threshold to 10 later or figure out how big the groups should be? 
    if count >= 4:
        # create the group
        cursor.execute(
            "INSERT INTO Match_Groups (event_id) VALUES (%s)",
            (event_id,),
        )
        db.commit()

        # IMPORTANT: get the group_id we just created
        group_id = cursor.lastrowid

        # assign all ungrouped matches for this event to this new group
        cursor.execute(
            """
            UPDATE Matches
               SET group_id = %s
             WHERE event_id = %s
               AND group_id IS NULL
            """,
            (group_id, event_id),
        )
        db.commit()

        return redirect(f"/group/{group_id}")

    return redirect("/events") '''


#group page
@app.route("/group/<int:group_id>")
def group(group_id): 
    cursor = db.cursor()
    
    #get the group based on the group id
    cursor.execute("select * from Match_Groups where group_id = %s", (group_id,))
    group = cursor.fetchone() #Does this work??
    
    
    #now get the event info
    cursor.execute("select * from Single_Events where event_id = %s", (group['event_id'],))
    event = cursor.fetchone()

    #get ALL the users together
    cursor.execute("select u.username from Matches m join Users u on m.username = u.username where m.event_id = %s", (group['event_id'],))
    users = cursor.fetchall()

    # messages in THIS group (newest last)
    cursor.execute("""
        SELECT messages_id, sender, message_content, time_stamp
        FROM Messages
        WHERE group_id = %s
        ORDER BY time_stamp ASC
    """, (group_id,))
    messages = cursor.fetchall()

    return render_template("group.html",
                        group=group, event=event,
                        users=users, messages=messages)


@app.route("/api/group/<int:group_id>/messages", methods=["GET", "POST"])
def api_group_messages(group_id):
    if "username" not in session:
        return jsonify({"error": "unauthorized"}), 401

    cursor = db.cursor()

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        body = (data.get("message") or "").strip()
        if not body:
            return jsonify({"error": "message is required"}), 400
        if len(body) > 300:
            body = body[:300]  # schema uses VARCHAR(300)

        # must belong to this group
        cursor.execute(
            "SELECT 1 FROM Matches WHERE group_id=%s AND username=%s LIMIT 1",
            (group_id, session["username"]),
        )
        if not cursor.fetchone():
            return jsonify({"error": "not a member of this group"}), 403

        cursor.execute(
            "INSERT INTO Messages (group_id, sender, message_content) VALUES (%s,%s,%s)",
            (group_id, session["username"], body),
        )
        db.commit()

        new_id = cursor.lastrowid
        cursor.execute(
            "SELECT messages_id, sender, message_content, time_stamp FROM Messages WHERE messages_id=%s",
            (new_id,),
        )
        r = cursor.fetchone()
        return jsonify({
            "id": r["messages_id"],
            "sender": r["sender"],
            "message": r["message_content"],
            "ts": r["time_stamp"].strftime("%Y-%m-%d %H:%M:%S") if r["time_stamp"] else None,
        }), 201

    # GET: list messages (support incremental polling by since_id)
    since_id = request.args.get("since_id", type=int)
    if since_id:
        cursor.execute(
            """
            SELECT messages_id, sender, message_content, time_stamp
            FROM Messages
            WHERE group_id = %s AND messages_id > %s
            ORDER BY time_stamp ASC
            """,
            (group_id, since_id),
        )
    else:
        cursor.execute(
            """
            SELECT messages_id, sender, message_content, time_stamp
            FROM Messages
            WHERE group_id = %s
            ORDER BY time_stamp ASC
            """,
            (group_id,),
        )
    rows = cursor.fetchall()
    return jsonify([
        {
            "id": r["messages_id"],
            "sender": r["sender"],
            "message": r["message_content"],
            "ts": r["time_stamp"].strftime("%Y-%m-%d %H:%M:%S") if r["time_stamp"] else None,
        }
        for r in rows
    ])

@app.route("/my_group")
def my_groups():
    if "username" not in session:
        return redirect("/login")

    username = session["username"]
    cursor = db.cursor()

    # Find groups this user belongs to via Matches → Match_Groups → Single_Events
    cursor.execute("""
        SELECT DISTINCT g.group_id, g.group_name, e.event_name
        FROM Matches m
        JOIN Match_Groups g ON m.group_id = g.group_id
        JOIN Single_Events e ON g.event_id = e.event_id
        WHERE m.username = %s
        ORDER BY g.group_id
    """, (username,))
    groups = cursor.fetchall()

    return render_template("my_group.html", groups=groups)

@app.route("/api/hybrid_recommendations")
def hybrid_recommendations():
    if "username" not in session:
        return jsonify({"error": "unauthorized"}), 401

    username = session["username"]
    cursor = db.cursor(DictCursor)

    # ----------------------------------------
    # 1) Get the user's interests
    # ----------------------------------------
    cursor.execute("""
        SELECT interest_id 
        FROM User_Interests
        WHERE username = %s
    """, (username,))
    user_interests = [row["interest_id"] for row in cursor.fetchall()]

    # If user has no interests → fallback to random
    if not user_interests:
        cursor.execute("""
            SELECT *
            FROM Single_Events
            ORDER BY RAND()
            LIMIT 20
        """)
        return jsonify(cursor.fetchall())

    # ----------------------------------------
    # 2) Find similar users by shared interests
    # ----------------------------------------
    cursor.execute("""
        SELECT ui2.username, COUNT(*) AS shared
        FROM User_Interests ui1
        JOIN User_Interests ui2
             ON ui1.interest_id = ui2.interest_id
        WHERE ui1.username = %s
          AND ui2.username <> %s
        GROUP BY ui2.username
        ORDER BY shared DESC
        LIMIT 10
    """, (username, username))

    similar_users = [row["username"] for row in cursor.fetchall()]

    # ----------------------------------------
    # 3) Events liked by similar users
    # rating = 1 means they swiped "Yes"
    # ----------------------------------------
    liked_events = []
    if similar_users:
        format_strings = ",".join(["%s"] * len(similar_users))
        cursor.execute(f"""
            SELECT DISTINCT event_id
            FROM User_Event_Ratings
            WHERE username IN ({format_strings})
              AND rating = 1
        """, similar_users)
        liked_events = [row["event_id"] for row in cursor.fetchall()]

    # ----------------------------------------
    # 4) Content-based: events matching user interests
    # (You need to eventually add an Event_Interests table)
    # For now: treat event_description + event_name as text match
    # ----------------------------------------
    if user_interests:
        # Fake content-based: using keyword search from Interests table
        cursor.execute("""
            SELECT interest_name
            FROM Interests
            WHERE interest_id IN (
                SELECT interest_id FROM User_Interests WHERE username = %s
            )
        """, (username,))
        keywords = [row["interest_name"] for row in cursor.fetchall()]
    else:
        keywords = []

    content_events = set()

    # simple keyword scan (update later if you add event tags)
    for kw in keywords:
        cursor.execute("""
            SELECT event_id
            FROM Single_Events
            WHERE event_name LIKE %s
               OR event_description LIKE %s
            LIMIT 20
        """, (f"%{kw}%", f"%{kw}%"))
        content_events.update([row["event_id"] for row in cursor.fetchall()])

    # ----------------------------------------
    # 5) Random exploration pool (ensures discovery)
    # ----------------------------------------
    cursor.execute("""
        SELECT event_id
        FROM Single_Events
        ORDER BY RAND()
        LIMIT 25
    """)
    random_pool = [row["event_id"] for row in cursor.fetchall()]

    # ----------------------------------------
    # 6) Combine events (unique)
    # ----------------------------------------
    combined_event_ids = set(liked_events) | set(content_events) | set(random_pool)

    if not combined_event_ids:
        return jsonify([])

    # ----------------------------------------
    # 7) Build hybrid score for each event
    # ----------------------------------------
    final_scores = {}

    for eid in combined_event_ids:
        score = 0

        # CF weight
        if eid in liked_events:
            score += 3

        # content match
        if eid in content_events:
            score += 2

        # slight random boost
        if eid in random_pool:
            score += 1

        final_scores[eid] = score

    # sort by score descending
    sorted_ids = sorted(final_scores.keys(), key=lambda x: final_scores[x], reverse=True)

    # fetch event details
    format_strings = ",".join(["%s"] * len(sorted_ids))
    cursor.execute(f"""
        SELECT *
        FROM Single_Events
        WHERE event_id IN ({format_strings})
    """, sorted_ids)

    events = cursor.fetchall()

    # reorder to match hybrid ranking
    event_map = {e["event_id"]: e for e in events}
    sorted_events = [event_map[eid] for eid in sorted_ids]

    return jsonify(sorted_events)


if __name__ == '__main__': 
    app.debug = True
    app.run(host='0.0.0.0', port=5024)
