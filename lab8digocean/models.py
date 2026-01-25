import sqlite3

# This class will handle creating the necessary tables in the database
class Schema:
    def __init__(self):
        self.conn = sqlite3.connect('todo.db')  # Connect to SQLite database
        self.create_user_table()  # Create the User table first
        self.create_to_do_table()  # Create the Todo table second

    def __del__(self):
        self.conn.commit()  # Commit any changes
        self.conn.close()   # Close the database connection

    # Create the "User" table in the database
    def create_user_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS "User" (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            Name TEXT NOT NULL,
            Email TEXT,
            CreatedOn DATE DEFAULT CURRENT_DATE
        );
        """
        self.conn.execute(query)

    # Create the "Todo" table in the database
    def create_to_do_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS "Todo" (
            id INTEGER PRIMARY KEY,
            Title TEXT,
            Description TEXT,
            _is_done BOOLEAN DEFAULT 0,
            _is_deleted BOOLEAN DEFAULT 0,
            CreatedOn DATE DEFAULT CURRENT_DATE,
            DueDate DATE,
            UserId INTEGER,
            FOREIGN KEY (UserId) REFERENCES User(_id)
        );
        """
        self.conn.execute(query)


# This class handles CRUD operations for the Todo items
class ToDoModel:
    TABLENAME = "Todo"

    def __init__(self):
        self.conn = sqlite3.connect('todo.db')  # Connect to SQLite database
        self.conn.row_factory = sqlite3.Row       # Return results as dictionaries

    def __del__(self):
        self.conn.commit()  # Commit any changes
        self.conn.close()   # Close the database connection

    # Get a Todo item by its ID
    def get_by_id(self, _id):
        where_clause = f"AND id={_id}"
        return self.list_items(where_clause)

    # Create a new Todo item
    def create(self, params):
        query = f'INSERT INTO {self.TABLENAME} ' \
                f'(Title, Description, DueDate, UserId) ' \
                f'VALUES ("{params.get("Title")}", "{params.get("Description")}", ' \
                f'"{params.get("DueDate")}", "{params.get("UserId")}")'
        result = self.conn.execute(query)
        return self.get_by_id(result.lastrowid)

    # Mark a Todo item as deleted (soft delete)
    def delete(self, item_id):
        query = f"UPDATE {self.TABLENAME} " \
                f"SET _is_deleted = 1 " \
                f"WHERE id = {item_id}"
        self.conn.execute(query)
        return self.list_items()

    # Update a Todo item
    def update(self, item_id, update_dict):
        set_query = ", ".join([f'{column} = "{value}"' for column, value in update_dict.items()])
        query = f"UPDATE {self.TABLENAME} " \
                f"SET {set_query} " \
                f"WHERE id = {item_id}"
        self.conn.execute(query)
        return self.get_by_id(item_id)

    # List all Todo items
    def list_items(self, where_clause=""):
        query = f"SELECT id, Title, Description, DueDate, _is_done " \
                f"FROM {self.TABLENAME} WHERE _is_deleted != 1 {where_clause}"
        result_set = self.conn.execute(query).fetchall()
        return [{column: row[i] for i, column in enumerate(result_set[0].keys())} for row in result_set]


# User class for managing User data
class User:
    TABLENAME = "User"

    def create(self, name, email):
        query = f'INSERT INTO {self.TABLENAME} ' \
                f'(Name, Email) ' \
                f'VALUES ("{name}", "{email}")'
        result = self.conn.execute(query)
        return result
