from flask import Flask, request, jsonify
import mysql.connector
import os

app = Flask(__name__)

# Connect to MySQL database
def get_db_connection():
    connection = mysql.connector.connect(
        host="mysql",  # MySQL service name (will be used by Kubernetes)
        user="root",
        password=os.getenv('MYSQL_ROOT_PASSWORD'),
        database="flaskapi"
    )
    return connection

@app.route('/users', methods=['GET'])
def get_users():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute('SELECT * FROM users')
    users = cursor.fetchall()
    cursor.close()
    connection.close()
    return jsonify(users)

@app.route('/user', methods=['POST'])
def create_user():
    data = request.get_json()
    user_name = data['user_name']
    user_email = data['user_email']
    user_password = data['user_password']
    
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute('INSERT INTO users (user_name, user_email, user_password) VALUES (%s, %s, %s)', 
                   (user_name, user_email, user_password))
    connection.commit()
    cursor.close()
    connection.close()
    return jsonify({"message": "User created successfully!"}), 201

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
