# Gmail --> Discord python3
import configparser
import os
import sys
import time
import json
import yaml
import logging
import requests
import click
from datetime import datetime
from pathlib import Path

from app.gmail_client import GmailClient
from app.filter_engine import FilterEngine
from app.notifier import Notifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

class GmailAgent:
    """Main local agent that reads Gmail and sends notifications"""
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()
        self.gmail = None
        self.filter_engine = FilterEngine(self.config.get("filters", []))
        self.notifier = Notifier(
            self.config['bot_url'],
            self.config['bot_token']
        )

        # State tracking
        self.last_click = None
        self.processed_ids = set()

    def _load_config(self):
        """Loads config from YAML file"""
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def _save_state(self):
        """Saves state email IDs to file"""
        state_file = self.config.get('state_file', 'agent-state.json')
        with open(state_file, 'w') as f:
            json.dump({
                'processed_ids': list(self.processed_ids),
                'last_check': self.last_click,
            }, f)

    def _load_state(self):
        """Loads processed email IDs from files"""
        state_file = self.config.get('state_file', 'agent-state.json')
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                data = json.load(f)
                self.processed_ids = set(data.get('processed_ids', []))
                self.last_click = data.get('last_check')

    def setup_gmail(self):
        """Initializes Gmail client with OAuth"""
        self.gmail = GmailClient()
        if not self.gmail.authenticate():
            logger.error("Failed to authenticate with Gmail")
            return False
        return True

    def process_email(self):
        """Process new emails and send notifications"""
        if not self.gmail:
            logger.error("Gmail client not initialized")
            return
        try:
            # Get unread emails
            messages = self.gmail.get_unread_message()
            logger.info(f"Found {len(messages)} unread emails")

            for msg in messages:
                msg_id = msg.get('id')

                # skip if already processed
                if msg_id in self.processed_ids:
                    continue

                # Get full message
                email_data = self.gmail.get_message(msg_id)
                if not email_data:
                    continue

                # Apply Filter
                if self.filter_engine.matches(email_data):
                    #send notification
                    self.notifier.send_notification(
                        channel_id=self.config['notification_channel'],
                        sender=self.config['notification_sender'],
                        subject=email_data.get['subject'],
                        preview=email_data.get('preview', ''),
                        date=email_data.get('date', '')
                    )

                    # Mark as processed
                    self.processed_ids.add(msg_id)
                    logger.info(f"Sent notification: {email_data['subject']}")
                else:
                    logger.debug(f"Skipped: {email_data['subject']}")

                # Mark as read (Optional)
                if self.config.get('mark_read', True):
                    self.gmail.mark_read(msg_id)

            #save state
            self.last_check = datetime.utcnow().isoformat()
            self._save_state()

        except Exception as e:
            logger.error(f"Error processing email: {e}")


