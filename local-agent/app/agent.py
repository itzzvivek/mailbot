# Gmail --> Discord python3
import configparser
import os
import sys
import time
import json
from email.policy import default

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

    def run(self, interval: int = 30):
        """Main loop"""
        logger.info("Gmail Agent Started")
        logger.info(f"Monitoring: {self.config['gmail_user']}")
        logger.info(f"Sending to: {self.config['bot_url']}")
        logger.info(f"Interval: {interval} seconds")

        self.load_state()
        self.setup_gmail()

        while True:
            try:
                self.process_email()
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                time.sleep(10)

            time.sleep(interval)

        def setup_mode(self):
            """Interactive setup mode"""
            click.echo("\n Gmail Agent Setup\n")

            #Get API Key
            api_key = click.prompt("Enter your API key", hide_input=True)

            # Get Discord channel ID
            channel_id = click.prompt("Enter Discord channel ID")

            # Get Gmail credentials
            gmail_user = click.prompt("Enter your Gmail Address")

            # Set up OAuth
            self.email = GmailClient()
            oauth_success = self.email.authenticate()

            if not oauth_success:
                click.echo("oauth setup failed")
                return

            # Get passcode
            passcode = click.prompt("Create a personal passcode", hide_input=True)
            passcode_confirm = click.prompt("Confirm your passcode", hide_input=True)

            if passcode != passcode_confirm:
                click.echo("Passcode do not match")
                return

            #save config
            config = {
                'gmail_user': gmail_user,
                'api_key': api_key,
                'bot_url': '**********',
                'discord_channel_id': channel_id,
                'filter':[],
                'mark_read':True,
                'state_file': 'agent-state.json'
            }

            config_path = click.prompt("Save config to", default="cofig.yaml")
            with open(config_path, 'w') as f:
                yaml.dump(config, f)

            # Connect bot with encryption token
            token = self.gmail.get_refresh_token()
            if token:
                response = requests.post(
                    f"{config['bot_url']}/conncet",
                    json={'oauth_token': token, 'passcode': passcode},
                    headers={'X-API-Key': api_key}
                )
                if response.status_code == 200:
                    click.echo("\n Gmail connected successfully")
                    click.echo("Token encrypted with your passcode")
                    click.echo("\nUse `python agent.py --start` to begin monitoring")
                else:
                    click.echo(f"\n Failed to connect: {response.text}")
            else:
                click.echo(" Failed to get OAuth token")


@click.command()
@click.option('--config', default='config.yaml', help='Configuration file path')
@click.option('--setup', is_flag=True, help='Run interactive setup')
@click.option('--start', is_flag=True, help='Start monitoring')
@click.option('--interval', default=30, help='Check interval in seconds')
def main(config, setup, start, interval):
    """Gmail → Discord Agent CLI"""

    if setup:
        agent = GmailAgent(config)
        agent.setup_mode()
        return

    if start:
        if not os.path.exists(config):
            click.echo(f"Config file not found: {config}")
            click.echo("Run `python agent.py --setup` first")
            return

        agent = GmailAgent(config)
        agent.run(interval)
        return

    click.echo("""
🔐 Gmail → Discord Agent

Commands:
  --setup    Interactive setup
  --start    Start monitoring
  --config   Config file path (default: config.yaml)
  --interval Check interval in seconds (default: 30)

Examples:
  python agent.py --setup
  python agent.py --start
  python agent.py --start --interval 15
    """)


if __name__ == "__main__":
    main()

