/* ---------- 1) Drop tables if created -----*/
DROP TABLE IF EXISTS Matches;
DROP TABLE IF EXISTS Messages;
DROP TABLE IF EXISTS Match_Groups;
DROP TABLE IF EXISTS Single_Events;
DROP TABLE IF EXISTS Venue ;
DROP TABLE IF EXISTS Users;

/* ---------- 2) create tables  ----- */
CREATE TABLE Users (
    username       			VARCHAR(50) PRIMARY KEY,
    email          			VARCHAR(100) NOT NULL UNIQUE,
    full_name      			VARCHAR(50) NOT NULL,
    user_password  			VARCHAR(50) NOT NULL,
    user_city      			VARCHAR(100) NOT NULL,
    user_state     			CHAR(2) NOT NULL,
	user_age				INT NOT NULL,
	user_gender 			CHAR(1) NOT NULL

) ENGINE=InnoDB;

CREATE TABLE Venue (
    venue_address     		VARCHAR(100) NOT NULL,
    venue_location 				VARCHAR(100) NOT NULL,
    PRIMARY KEY (venue_address, venue_location)
) ENGINE=InnoDB;

CREATE TABLE Single_Events (
    event_id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_name          VARCHAR(100) NOT NULL,
    event_description   TEXT,
    venue_address       VARCHAR(100) NOT NULL,
    venue_location      VARCHAR(100) NOT NULL,
    link                TEXT,
    popularity          BIGINT DEFAULT 0,
    FOREIGN KEY (venue_address, venue_location) REFERENCES Venue(venue_address, venue_location)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE Match_Groups (
    group_id        BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    group_name      VARCHAR(100) NOT NULL DEFAULT 'NEW GROUP!',
    event_id        BIGINT UNSIGNED NOT NULL,
    FOREIGN KEY (event_id) REFERENCES Single_Events(event_id)
        ON DELETE CASCADE 
        ON UPDATE CASCADE

) ENGINE=InnoDB;

CREATE TABLE Matches (
    match_id  BIGINT UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    event_id  BIGINT UNSIGNED NOT NULL,
    username  VARCHAR(50) NOT NULL,
    group_id  BIGINT UNSIGNED NULL,

    FOREIGN KEY (event_id) REFERENCES Single_Events(event_id)
        ON DELETE CASCADE 
        ON UPDATE CASCADE,
    FOREIGN KEY (username) REFERENCES Users(username)
        ON DELETE CASCADE 
        ON UPDATE CASCADE,
    FOREIGN KEY (group_id) REFERENCES Match_Groups(group_id)
        ON DELETE CASCADE 
        ON UPDATE CASCADE,
    CONSTRAINT unique_user_group UNIQUE (username, group_id)
) ENGINE=InnoDB;

CREATE TABLE Messages (
    messages_id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    sender              VARCHAR(50) NULL,                 
    message_content     VARCHAR(300) NOT NULL,
    time_stamp          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    group_id            BIGINT UNSIGNED,
    FOREIGN KEY (sender) REFERENCES Users(username)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    FOREIGN KEY (group_id) REFERENCES Match_Groups(group_id)
        ON DELETE CASCADE 
        ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE Interests (
    interest_id INT AUTO_INCREMENT PRIMARY KEY,
    interest_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE User_Interests (
    username VARCHAR(50) NOT NULL,
    interest_id INT NOT NULL,
    PRIMARY KEY (username, interest_id),
    FOREIGN KEY (username) REFERENCES Users(username)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (interest_id) REFERENCES Interests(interest_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE User_Event_Ratings (
    username VARCHAR(50) NOT NULL,
    event_id BIGINT UNSIGNED NOT NULL,
    rating INT NOT NULL,  -- 1 = yes, 2 = attended
    PRIMARY KEY (username, event_id),
    FOREIGN KEY (username) REFERENCES Users(username)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (event_id) REFERENCES Single_Events(event_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
