from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello_world():

    return 'Hello MSOE'

# This is the "Enhancement"
@app.route('/status')
def get_status():
    return jsonify({
        "status": "online",
        "message": "Microservice enhanced successfully!",
        "version": "2.0"
    })

if __name__ == "__main__":
	app.run(host='0.0.0.0', port=8080)
