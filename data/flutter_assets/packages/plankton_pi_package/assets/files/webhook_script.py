import flask
from flask import request, jsonify
import queue
import threading
import time
import sys
import json
import logging

app = flask.Flask(__name__)
action_queue = queue.Queue()

cli = sys.modules['flask.cli']
cli.show_server_banner = lambda *x: None
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

def clear_queue():
    time.sleep(1)
    while not action_queue.empty():
        action_queue.get()

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        data = request.json
        action = data.get('action')

        if action:
            action_queue.put(action)
            threading.Thread(target=clear_queue).start()
            print(json.dumps({"method": "action", "action": action}))
            sys.stdout.flush()
            return jsonify({'status': 'success', 'message': f'Action {action} received'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'No action specified'}), 400

if __name__ == '__main__':
    print(json.dumps({"method": "ready"}))
    sys.stdout.flush()
    app.run(host='0.0.0.0', port=5000, debug=False)
