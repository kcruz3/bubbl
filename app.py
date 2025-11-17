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

    cursor = db.cursor(DictCursor)  # 👈 important
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

    cursor = db.cursor(DictCursor)

    if choice == "yes":
        cursor.execute(
            """
            UPDATE Single_Events
               SET popularity = COALESCE(popularity, 0) + 1
             WHERE event_id = %s
            """,
            (event_id,),
        )
        db.commit()

    return jsonify({"status": "ok", "choice": choice})

#create a match based on a selected event
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

    return redirect("/events")


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



if __name__ == '__main__': 
    app.debug = True
    app.run(host='0.0.0.0', port=5024)
