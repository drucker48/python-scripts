
# Author: D Rucker | IT Engineer 
# Description: This script archives Slack channels that have been inactive for a specified number of days.
# It uses the Slack Web API and requires a bot token with appropriate scopes.

import csv
import datetime
import logging
import os
import sys
import time
from dotenv import load_dotenv
from enum import Enum
from slack_sdk import WebClient


# Load environment variables from slack.env file
load_dotenv('slack.env')


class ProcessStatus(Enum):
    """Status enum for channel processing results."""
    PROTECTED = "protected"
    ACTIVE = "active"
    ARCHIVED = "archived"
    FAILED = "failed"

########### VARIABLES TO SET ############

LOGGER = logging.getLogger("slack-archiver")

ARCHIVE_LAST_MESSAGE_AGE_DAYS = 90  # Number of days of inactivity before archiving

# Rate limiting configuration
API_DELAY_SECONDS = float(os.environ.get('SLACK_API_DELAY', '1.0'))  # Delay between API calls
BATCH_DELAY_SECONDS = float(os.environ.get('SLACK_BATCH_DELAY', '5.0'))  # Delay every 10 channels

# Channels that should never be archived (case-insensitive matching)
PROTECTED_CHANNELS = [
    'announcements',
    'general'
]

# Pre-compute lowercased set for O(1) lookup performance
PROTECTED_CHANNELS_LOWER = {name.lower() for name in PROTECTED_CHANNELS}

# Configurable output directory for CSV files
OUTPUT_DIR = os.environ.get('SLACK_ARCHIVER_OUTPUT_DIR', './archived_channels')


########### END VARIABLES TO SET ############


########### FUNCTIONS ###########
def ensure_log_directory(log_file_path):
    """Ensure the log directory exists, create it if it doesn't."""
    log_dir = os.path.dirname(log_file_path)
    try:
        os.makedirs(log_dir, exist_ok=True)
        return log_file_path
    except OSError as e:
        # Fallback to current directory if we can't create the log directory
        fallback_path = './slack-archiver.log'
        print(f"Failed to create log directory {log_dir}: {e}")
        print(f"Using fallback log file: {fallback_path}")
        return fallback_path

def setup_logger():
    # Use environment variable or fallback to current directory
    log_file_default = os.environ.get('SLACK_ARCHIVER_LOG_FILE', './slack-archiver.log')
    log_file_path = ensure_log_directory(log_file_default)
    logging.basicConfig(
        filename=log_file_path,
        level=logging.DEBUG,
        filemode="a",
        datefmt="%Y-%m-%d %H:%M:%S",
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().addHandler(logging.StreamHandler(stream=sys.stdout))

# Token needs the following scopes:
# channels:read
# channels:history
# channels:join
# channels:manage
def get_api_key():
    token = os.environ.get("SLACK_API_TOKEN", None)
    if token is None:
        raise ValueError("SLACK_API_TOKEN not found in environment variables. Please check your slack.env file.")
    return token


def is_protected_channel(channel_name):
    """Check if channel name is in the protected channels list."""
    return channel_name.lower() in PROTECTED_CHANNELS_LOWER


def is_slack_connect_channel(channel):
    """Check if channel is a Slack Connect channel (shared with external orgs)."""
    return channel.get('is_ext_shared', False)


def leave_channel_if_needed(client, channel_id, channel_name):
    """Leave channel if bot is a member and it's not a protected channel."""
    try:
        # Don't leave protected channels
        if is_protected_channel(channel_name):
            LOGGER.info(f"Not leaving protected channel #{channel_name}")
            return
            
        client.conversations_leave(channel=channel_id)
        LOGGER.info(f"Left active channel #{channel_name}")
        time.sleep(API_DELAY_SECONDS)  # Rate limiting delay
    except Exception as e:
        LOGGER.warning(f"Could not leave channel #{channel_name}: {e}")


def ensure_output_directory(output_dir):
    """Ensure the output directory exists, create it if it doesn't."""
    try:
        os.makedirs(output_dir, exist_ok=True)
        LOGGER.info(f"Output directory ensured: {output_dir}")
        return output_dir
    except OSError as e:
        LOGGER.error(f"Failed to create output directory {output_dir}: {e}")
        # Fallback to current directory
        fallback_dir = './'
        LOGGER.warning(f"Using fallback directory: {fallback_dir}")
        return fallback_dir


def channel_has_recent_messages(client, my_user_id, channel_id, channel_name="Unknown"):
    """Check if channel has recent messages within the specified timeframe."""
    try:
        # Calculate fresh timestamp to avoid stale comparisons
        oldest_message_time = (
            datetime.datetime.now() - datetime.timedelta(days=ARCHIVE_LAST_MESSAGE_AGE_DAYS)
        ).timestamp()
        
        # Getting up to 2 messages younger than ARCHIVE_LAST_MESSAGE_AGE_DAYS
        response = client.conversations_history(
            channel=channel_id,
            oldest=oldest_message_time,
            limit=2
        )
        # Add small delay after API call
        time.sleep(0.5)  # Half second delay for message history calls
        # Filter out message about our bot joining this channel
        real_messages = list(filter(lambda m: m.get('user') != my_user_id, response['messages']))
        # If we found at least one - return True, if not - False
        has_messages = len(real_messages) > 0
        if not has_messages:
            LOGGER.info(f"#{channel_name}: No recent messages found (inactive for {ARCHIVE_LAST_MESSAGE_AGE_DAYS}+ days)")
        return has_messages
    except Exception as e:
        LOGGER.error(f"Error checking messages for channel #{channel_name} ({channel_id}): {e}")
        LOGGER.warning(f"#{channel_name}: Treating as active due to error (safety fallback)")
        # Return True to be safe - don't archive if we can't check
        return True


def get_all_channels(client):
    """Retrieve all non-archived channels using pagination."""
    all_channels = []
    next_cursor = None
    
    try:
        while True:
            response = client.conversations_list(
                exclude_archived=True, 
                limit=200,
                cursor=next_cursor
            )
            all_channels.extend(response['channels'])
            
            if response.get('response_metadata') and response['response_metadata'].get('next_cursor'):
                next_cursor = response['response_metadata']['next_cursor']
            else:
                break
        
        LOGGER.info(f"Successfully retrieved {len(all_channels)} channels")
        return all_channels
    
    except Exception as e:
        LOGGER.error(f"Error retrieving channels: {e}")
        raise


def process_channel(client, my_user_id, channel, csv_writer):
    """Process a single channel: check activity and archive if inactive.
    
    Returns:
        ProcessStatus: The result of processing the channel
    """
    channel_name = channel.get('name', 'Unknown')
    channel_id = channel.get('id', 'Unknown')
    
    try:
        # Check if this is a Slack Connect channel
        if is_slack_connect_channel(channel):
            LOGGER.info(f"#{channel_name}: Slack Connect channel (external) - skipping")
            return ProcessStatus.PROTECTED
        
        # Check if this is a protected channel
        if is_protected_channel(channel_name):
            LOGGER.info(f"#{channel_name}: protected channel - skipping")
            return ProcessStatus.PROTECTED
        
        # Check if channel has recent activity
        if channel_has_recent_messages(client, my_user_id, channel_id, channel_name):
            LOGGER.info(f"#{channel_name}: has recent messages - keeping active")
            
            # Leave the channel since it's active and we don't need to monitor it
            if channel.get('is_member', False):
                leave_channel_if_needed(client, channel_id, channel_name)
            
            return ProcessStatus.ACTIVE
        else:
            LOGGER.info(f"#{channel_name}: archiving")
            
            # Store timestamp once for consistent timestamps across operations
            archive_timestamp = datetime.datetime.now()
            
            try:
                client.conversations_archive(channel=channel_id)
                LOGGER.info(f"#{channel_name}: successfully archived")
                time.sleep(API_DELAY_SECONDS)  # Rate limiting delay after archive
                
                # Log to CSV
                try:
                    csv_writer.writerow({
                        'channel_name': channel_name,
                        'channel_id': channel_id,
                        'archived_timestamp': archive_timestamp.isoformat(),
                        'created_date': datetime.datetime.fromtimestamp(channel.get('created', 0)).isoformat() if channel.get('created') else 'Unknown',
                        'member_count': channel.get('num_members', 'Unknown')
                    })
                except Exception as csv_error:
                    LOGGER.error(f"Error writing to CSV for channel #{channel_name}: {csv_error}")
                
                return ProcessStatus.ARCHIVED
                
            except Exception as archive_error:
                LOGGER.error(f"Error archiving channel #{channel_name}: {archive_error}")
                return ProcessStatus.FAILED
                
    except Exception as e:
        LOGGER.error(f"Error processing channel #{channel_name} ({channel_id}): {e}")
        return ProcessStatus.FAILED


def archive_inactive_channels(client, my_user_id):
    """Main function to orchestrate the archiving process."""
    try:
        # Store timestamp once for consistent timestamps across operations
        process_timestamp = datetime.datetime.now()
        
        LOGGER.info(f"Starting channel archival process...")
        LOGGER.info(f"Archiving channels with no messages in the last {ARCHIVE_LAST_MESSAGE_AGE_DAYS} days")
        
        # Get all channels with error handling
        try:
            channels = get_all_channels(client)
            LOGGER.info(f"Found {len(channels)} channels to process")
        except Exception as e:
            LOGGER.error(f"Failed to retrieve channels: {e}")
            return
        
        # Ensure output directory exists and create CSV file path
        output_dir = ensure_output_directory(OUTPUT_DIR)
        csv_filename = os.path.join(output_dir, f"archived_channels_{process_timestamp.strftime('%Y%m%d_%H%M%S')}.csv")
        
        LOGGER.info(f"CSV output file: {csv_filename}")
        
        try:
            with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['channel_name', 'channel_id', 'archived_timestamp', 'created_date', 'member_count']
                csv_writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                csv_writer.writeheader()
                
                archived_count = 0
                failed_count = 0
                protected_count = 0
                active_count = 0
                
                for i, channel in enumerate(channels):
                    try:
                        channel_name = channel.get('name', 'Unknown')
                        channel_id = channel.get('id', 'Unknown')
                        
                        # Add batch delay every 10 channels to avoid overwhelming the API
                        if i > 0 and i % 10 == 0:
                            LOGGER.info(f"Processed {i} channels, pausing for {BATCH_DELAY_SECONDS}s...")
                            time.sleep(BATCH_DELAY_SECONDS)
                        
                        # Join channel if we're not already a member (skip protected and Slack Connect channels)
                        if not channel.get('is_member', False) and not is_protected_channel(channel_name) and not is_slack_connect_channel(channel):
                            try:
                                client.conversations_join(channel=channel_id)
                                LOGGER.debug(f"Joined channel #{channel_name}")
                                time.sleep(API_DELAY_SECONDS)  # Rate limiting delay
                            except Exception as join_error:
                                LOGGER.warning(f"Could not join channel #{channel_name}: {join_error}")
                                # Continue processing even if join fails
                        
                        # Process channel and count results based on status
                        status = process_channel(client, my_user_id, channel, csv_writer)
                        
                        # Add small delay between channel processing
                        time.sleep(API_DELAY_SECONDS)
                        
                        if status == ProcessStatus.ARCHIVED:
                            archived_count += 1
                        elif status == ProcessStatus.PROTECTED:
                            protected_count += 1
                        elif status == ProcessStatus.ACTIVE:
                            active_count += 1
                        elif status == ProcessStatus.FAILED:
                            failed_count += 1
                        
                    except Exception as channel_error:
                        LOGGER.error(f"Failed to process channel: {channel_error}")
                        failed_count += 1
                        continue
                
                # Ensure all data is written to disk
                csvfile.flush()
        
        except IOError as file_error:
            LOGGER.error(f"Error creating or writing to CSV file {csv_filename}: {file_error}")
            return
        
        LOGGER.info(f"Finished processing all channels.")
        LOGGER.info(f"Results: {archived_count} archived, {protected_count} protected (skipped), {active_count} active (left), {failed_count} failed")
        LOGGER.info(f"Details logged to: {csv_filename}")
        
    except Exception as e:
        LOGGER.error(f"Unexpected error in archive_inactive_channels: {e}")
        raise


if __name__ == "__main__":
    try:
        setup_logger()
        
        # Initialize API token after logger is set up
        try:
            slack_api_token = get_api_key()
        except ValueError as token_error:
            LOGGER.error(f"Token initialization failed: {token_error}")
            sys.exit(1)
        
        # Initialize Slack client and authenticate
        try:
            client = WebClient(
                token=slack_api_token,
                timeout=30  # Timeout for API requests
            )
            my_user_id = client.auth_test()['user_id']
            LOGGER.info(f"Successfully authenticated as user ID: {my_user_id}")
            LOGGER.info(f"Rate limiting configuration: API delay={API_DELAY_SECONDS}s, Batch delay={BATCH_DELAY_SECONDS}s")
        except Exception as auth_error:
            LOGGER.error(f"Authentication failed: {auth_error}")
            print(f"Authentication failed: {auth_error}")
            print("Please check your SLACK_API_TOKEN and ensure it has the required scopes.")
            sys.exit(1)
        
        # Run the main archival process
        archive_inactive_channels(client, my_user_id)
        
    except KeyboardInterrupt:
        LOGGER.info("Script interrupted by user")
        sys.exit(0)
    except Exception as e:
        LOGGER.error(f"Script failed with unexpected error: {e}")
        sys.exit(1)
