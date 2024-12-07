import sys
import json
import logging
import os
import time
import firebase_admin
from firebase_admin import credentials, firestore

# Set up logging
log_dir = os.path.expanduser('~/plankton_logs')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, 'firebase_listener.log'),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Also log to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(console_handler)

# Global variable for device ID and Firebase credentials
DEVICE_ID = None
firebase_creds = None

def get_device_id():
    """Get the device ID from command-line arguments."""
    global DEVICE_ID
    if len(sys.argv) > 1:
        return sys.argv[1]
    logging.error("No device ID provided")
    sys.exit(1)

def get_firebase_creds():
    """Get the Firebase credentials from command-line arguments."""
    global firebase_creds
    if len(sys.argv) > 2:
        firebase_creds = json.loads(sys.argv[2])
        return firebase_creds
    logging.error("No Firebase credentials provided")
    sys.exit(1)

def handle_document_change(doc_snapshot, changes, read_time):
    """Callback function to handle document changes in Firebase."""
    for change in changes:
        if change.type.name == 'MODIFIED':
            try:
                data = change.document.to_dict()
                action = data.get('action')
                if action:
                    logging.info(f"Detected action change: {action}")
                    print(json.dumps({"method": "action", "action": action}))
                    sys.stdout.flush()

                    firestore.client().collection('raspiDeviceIds').document(DEVICE_ID).update({
                        'action': firestore.DELETE_FIELD
                    })
                    logging.info("Deleted action field after processing")
            except Exception as e:
                logging.error(f"Error processing document change: {e}")
                # Output error to stdout in JSON format
                print(json.dumps({"status": "error", "message": str(e)}))
                sys.stdout.flush()

def start_firebase_listener():
    """Start the Firebase listener for the device."""
    global DEVICE_ID
    DEVICE_ID = get_device_id()
    creds = get_firebase_creds()

    logging.info(f"Starting Firebase listener for device: {DEVICE_ID}")
    logging.info("Initializing Firebase Admin with provided credentials.")

    try:
        # Initialize Firebase Admin SDK with provided credentials
        cred = credentials.Certificate(creds)
        firebase_admin.initialize_app(cred)
        db = firestore.client()

        # Listen to the document with the device ID
        doc_ref = db.collection('raspiDeviceIds').document(DEVICE_ID)

        # Create document if it doesn't exist
        if not doc_ref.get().exists:
            doc_ref.set({
                'deviceId': DEVICE_ID,
                'createdAt': firestore.SERVER_TIMESTAMP
            })

        # Start listening for changes
        doc_watch = doc_ref.on_snapshot(handle_document_change)
        logging.info(f"Firebase listener started for device: {DEVICE_ID}")

        # Output 'ready' message
        print(json.dumps({"status": "ready", "message": "Firebase listener initialized"}))
        sys.stdout.flush()
    except Exception as e:
        logging.error(f"Error initializing Firebase listener: {e}")
        # Output error to stdout in JSON format
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.stdout.flush()
        sys.exit(1)

if __name__ == '__main__':
    logging.info("Firebase listener script started")
    start_firebase_listener()

    # Keep the script running
    while True:
        time.sleep(60)
