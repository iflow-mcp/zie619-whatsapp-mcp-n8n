import sqlite3
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
import os.path
import requests
import json
import socket
import sys

MESSAGES_DB_PATH = "/app/store/messages.db"

# Try multiple ways to connect to the bridge
def get_bridge_url():
    """Get the correct URL for the WhatsApp bridge with fallback options."""
    # Try hostname first (preferred)
    try:
        socket.gethostbyname('whatsapp-bridge')
        return "http://whatsapp-bridge:8080/api"
    except socket.gaierror:
        pass

    # Based on the diagnostic, try the actual network range
    # Try 172.18.0.x first (automation-stack_internal network)
    for ip in ['172.18.0.4', '172.18.0.3', '172.18.0.2', '172.19.0.2', '172.20.0.2', '172.17.0.2']:
        try:
            response = requests.get(f"http://{ip}:8080/api/health", timeout=2)
            if response.status_code == 200:
                print(f"Bridge found at IP: {ip}", file=sys.stderr)
                return f"http://{ip}:8080/api"
        except:
            continue

    # Default fallback
    return "http://whatsapp-bridge:8080/api"

# Initialize with dynamic detection
WHATSAPP_API_BASE_URL = None

def get_api_url():
    """Get the API URL, detecting it dynamically if needed."""
    global WHATSAPP_API_BASE_URL
    if WHATSAPP_API_BASE_URL is None:
        WHATSAPP_API_BASE_URL = get_bridge_url()
    return WHATSAPP_API_BASE_URL

# Add flag for demo/testing mode
DEMO_MODE = os.environ.get('WHATSAPP_DEMO_MODE', 'false').lower() == 'true'

@dataclass
class Message:
    timestamp: datetime
    sender: str
    content: str
    is_from_me: bool
    chat_jid: str
    id: str
    chat_name: Optional[str] = None
    media_type: Optional[str] = None

@dataclass
class Chat:
    jid: str
    name: Optional[str]
    last_message_time: Optional[datetime]
    last_message: Optional[str] = None
    last_sender: Optional[str] = None
    last_is_from_me: Optional[bool] = None

    @property
    def is_group(self) -> bool:
        """Determine if chat is a group based on JID pattern."""
        return self.jid.endswith("@g.us")

@dataclass
class Contact:
    phone_number: str
    name: Optional[str]
    jid: str

@dataclass
class MessageContext:
    message: Message
    before: List[Message]
    after: List[Message]

def get_sender_name(sender_jid: str) -> str:
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        # First try matching by exact JID
        cursor.execute("""
            SELECT name
            FROM chats
            WHERE jid = ?
            LIMIT 1
        """, (sender_jid,))

        result = cursor.fetchone()

        # If no result, try looking for the number within JIDs
        if not result:
            # Extract phone number from JID
            phone_part = sender_jid.split('@')[0]
            cursor.execute("""
                SELECT name
                FROM chats
                WHERE jid LIKE ?
                LIMIT 1
            """, (f"%{phone_part}%",))
            result = cursor.fetchone()

        conn.close()

        if result and result[0]:
            return result[0]
        else:
            return sender_jid
    except Exception as e:
        print(f"Error getting sender name: {e}", file=sys.stderr)
        return sender_jid

def list_messages(
    after: Optional[str] = None,
    before: Optional[str] = None,
    sender_phone_number: Optional[str] = None,
    chat_jid: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_context: bool = True,
    context_before: int = 1,
    context_after: int = 1
) -> List[Dict[str, Any]]:
    """Get WhatsApp messages matching specified criteria with optional context."""
    if DEMO_MODE:
        # Return demo messages for testing
        return [
            {
                "id": "demo_msg_1",
                "timestamp": datetime.now().isoformat(),
                "sender": "1234567890@s.whatsapp.net",
                "sender_name": "Demo Contact",
                "content": "This is a demo message for testing",
                "is_from_me": False,
                "chat_jid": "1234567890@s.whatsapp.net",
                "chat_name": "Demo Contact",
                "media_type": None
            }
        ]

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        # Build query
        query_parts = ["SELECT id, timestamp, sender_jid, content, is_from_me, chat_jid, media_type FROM messages WHERE 1=1"]
        params = []

        if after:
            query_parts.append("AND timestamp > ?")
            params.append(after)

        if before:
            query_parts.append("AND timestamp < ?")
            params.append(before)

        if sender_phone_number:
            query_parts.append("AND sender_jid LIKE ?")
            params.append(f"%{sender_phone_number}%")

        if chat_jid:
            query_parts.append("AND chat_jid = ?")
            params.append(chat_jid)

        if query:
            query_parts.append("AND content LIKE ?")
            params.append(f"%{query}%")

        # Add ordering and pagination
        query_parts.append("ORDER BY timestamp DESC")
        query_parts.append(f"LIMIT {limit}")
        query_parts.append(f"OFFSET {page * limit}")

        cursor.execute(" ".join(query_parts), params)
        rows = cursor.fetchall()

        messages = []
        for row in rows:
            msg_id, timestamp, sender_jid, content, is_from_me, chat_jid, media_type = row
            messages.append({
                "id": msg_id,
                "timestamp": timestamp,
                "sender": sender_jid,
                "sender_name": get_sender_name(sender_jid),
                "content": content,
                "is_from_me": bool(is_from_me),
                "chat_jid": chat_jid,
                "chat_name": get_sender_name(chat_jid),
                "media_type": media_type
            })

        conn.close()
        return messages

    except Exception as e:
        print(f"Error listing messages: {e}", file=sys.stderr)
        return []

def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active"
) -> List[Dict[str, Any]]:
    """Get WhatsApp chats matching specified criteria."""
    if DEMO_MODE:
        # Return demo chats for testing
        return [
            {
                "jid": "1234567890@s.whatsapp.net",
                "name": "Demo Contact",
                "last_message_time": datetime.now().isoformat(),
                "last_message": "This is a demo message",
                "last_sender": "1234567890@s.whatsapp.net",
                "last_is_from_me": False,
                "is_group": False
            }
        ]

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        # Build query
        query_parts = ["SELECT jid, name, last_message_time FROM chats WHERE 1=1"]
        params = []

        if query:
            query_parts.append("AND (name LIKE ? OR jid LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        # Add ordering
        if sort_by == "last_active":
            query_parts.append("ORDER BY last_message_time DESC")
        else:
            query_parts.append("ORDER BY name ASC")

        # Add pagination
        query_parts.append(f"LIMIT {limit}")
        query_parts.append(f"OFFSET {page * limit}")

        cursor.execute(" ".join(query_parts), params)
        rows = cursor.fetchall()

        chats = []
        for row in rows:
            jid, name, last_message_time = row

            chat_data = {
                "jid": jid,
                "name": name or jid,
                "last_message_time": last_message_time,
                "is_group": jid.endswith("@g.us")
            }

            # Optionally include last message
            if include_last_message:
                cursor.execute("""
                    SELECT content, sender_jid, is_from_me
                    FROM messages
                    WHERE chat_jid = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (jid,))
                msg_row = cursor.fetchone()
                if msg_row:
                    chat_data["last_message"] = msg_row[0]
                    chat_data["last_sender"] = msg_row[1]
                    chat_data["last_is_from_me"] = bool(msg_row[2])

            chats.append(chat_data)

        conn.close()
        return chats

    except Exception as e:
        print(f"Error listing chats: {e}", file=sys.stderr)
        return []

def search_contacts(query: str) -> List[Contact]:
    """Search for contacts by name or phone number."""
    if DEMO_MODE:
        # Return demo contacts for testing
        return [
            Contact(
                phone_number="1234567890",
                name="Demo Contact",
                jid="1234567890@s.whatsapp.net"
            )
        ]

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT
                CASE
                    WHEN jid LIKE '%@s.whatsapp.net' THEN substr(jid, 1, length(jid) - 12)
                    ELSE jid
                END as phone_number,
                name,
                jid
            FROM chats
            WHERE name LIKE ? OR jid LIKE ?
            LIMIT 20
        """, (f"%{query}%", f"%{query}%"))

        rows = cursor.fetchall()
        contacts = [Contact(phone_number=row[0], name=row[1], jid=row[2]) for row in rows]

        conn.close()
        return contacts

    except Exception as e:
        print(f"Error searching contacts: {e}", file=sys.stderr)
        return []

def get_chat(chat_jid: str, include_last_message: bool = True) -> Optional[Chat]:
    """Get chat metadata by JID."""
    if DEMO_MODE:
        return Chat(
            jid="1234567890@s.whatsapp.net",
            name="Demo Contact",
            last_message_time=datetime.now()
        )

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name, last_message_time
            FROM chats
            WHERE jid = ?
            LIMIT 1
        """, (chat_jid,))

        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        name, last_message_time = row
        chat = Chat(jid=chat_jid, name=name, last_message_time=last_message_time)

        # Optionally include last message
        if include_last_message:
            cursor.execute("""
                SELECT content, sender_jid, is_from_me
                FROM messages
                WHERE chat_jid = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (chat_jid,))
            msg_row = cursor.fetchone()
            if msg_row:
                chat.last_message = msg_row[0]
                chat.last_sender = msg_row[1]
                chat.last_is_from_me = bool(msg_row[2])

        conn.close()
        return chat

    except Exception as e:
        print(f"Error getting chat: {e}", file=sys.stderr)
        return None

def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get direct chat by contact phone number."""
    if DEMO_MODE:
        return {
            "jid": "1234567890@s.whatsapp.net",
            "name": "Demo Contact",
            "last_message_time": datetime.now().isoformat(),
            "is_group": False
        }

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT jid, name, last_message_time
            FROM chats
            WHERE jid LIKE ?
            LIMIT 1
        """, (f"{sender_phone_number}@s.whatsapp.net",))

        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        jid, name, last_message_time = row

        conn.close()
        return {
            "jid": jid,
            "name": name or jid,
            "last_message_time": last_message_time,
            "is_group": False
        }

    except Exception as e:
        print(f"Error getting direct chat: {e}", file=sys.stderr)
        return None

def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all chats involving a specific contact."""
    if DEMO_MODE:
        return [
            {
                "jid": "1234567890@s.whatsapp.net",
                "name": "Demo Contact",
                "last_message_time": datetime.now().isoformat(),
                "is_group": False
            }
        ]

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT c.jid, c.name, c.last_message_time
            FROM chats c
            WHERE c.jid = ?
            ORDER BY c.last_message_time DESC
            LIMIT ? OFFSET ?
        """, (jid, limit, page * limit))

        rows = cursor.fetchall()
        chats = [{
            "jid": row[0],
            "name": row[1] or row[0],
            "last_message_time": row[2],
            "is_group": row[0].endswith("@g.us")
        } for row in rows]

        conn.close()
        return chats

    except Exception as e:
        print(f"Error getting contact chats: {e}", file=sys.stderr)
        return []

def get_last_interaction(jid: str) -> str:
    """Get most recent message involving a contact."""
    if DEMO_MODE:
        return "Demo message for testing"

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT content
            FROM messages
            WHERE chat_jid = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (jid,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return row[0]
        else:
            return None

    except Exception as e:
        print(f"Error getting last interaction: {e}", file=sys.stderr)
        return None

def get_message_context(
    message_id: str,
    before: int = 5,
    after: int = 5
) -> Dict[str, Any]:
    """Get context around a specific message."""
    if DEMO_MODE:
        return {
            "message": {
                "id": "demo_msg_1",
                "content": "Demo message",
                "timestamp": datetime.now().isoformat()
            },
            "before": [],
            "after": []
        }

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        # Get the target message
        cursor.execute("""
            SELECT id, timestamp, sender_jid, content, is_from_me, chat_jid, media_type
            FROM messages
            WHERE id = ?
            LIMIT 1
        """, (message_id,))

        target_row = cursor.fetchone()
        if not target_row:
            conn.close()
            return None

        msg_id, timestamp, sender_jid, content, is_from_me, chat_jid, media_type = target_row

        target_msg = {
            "id": msg_id,
            "timestamp": timestamp,
            "sender": sender_jid,
            "sender_name": get_sender_name(sender_jid),
            "content": content,
            "is_from_me": bool(is_from_me),
            "chat_jid": chat_jid,
            "chat_name": get_sender_name(chat_jid),
            "media_type": media_type
        }

        # Get messages before
        cursor.execute("""
            SELECT id, timestamp, sender_jid, content, is_from_me, chat_jid, media_type
            FROM messages
            WHERE chat_jid = ? AND timestamp < ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (chat_jid, timestamp, before))

        before_messages = []
        for row in cursor.fetchall():
            before_messages.append({
                "id": row[0],
                "timestamp": row[1],
                "sender": row[2],
                "sender_name": get_sender_name(row[2]),
                "content": row[3],
                "is_from_me": bool(row[4]),
                "chat_jid": row[5],
                "chat_name": get_sender_name(row[5]),
                "media_type": row[6]
            })

        before_messages.reverse()  # Reverse to get chronological order

        # Get messages after
        cursor.execute("""
            SELECT id, timestamp, sender_jid, content, is_from_me, chat_jid, media_type
            FROM messages
            WHERE chat_jid = ? AND timestamp > ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (chat_jid, timestamp, after))

        after_messages = []
        for row in cursor.fetchall():
            after_messages.append({
                "id": row[0],
                "timestamp": row[1],
                "sender": row[2],
                "sender_name": get_sender_name(row[2]),
                "content": row[3],
                "is_from_me": bool(row[4]),
                "chat_jid": row[5],
                "chat_name": get_sender_name(row[5]),
                "media_type": row[6]
            })

        conn.close()

        return {
            "message": target_msg,
            "before": before_messages,
            "after": after_messages
        }

    except Exception as e:
        print(f"Error getting message context: {e}", file=sys.stderr)
        return None

def send_message(recipient: str, message: str) -> Tuple[bool, str]:
    """Send a WhatsApp message."""
    if DEMO_MODE:
        return True, "Demo mode: Message would be sent to " + recipient

    try:
        api_url = get_api_url()
        response = requests.post(
            f"{api_url}/send-message",
            json={"recipient": recipient, "message": message},
            timeout=10
        )

        if response.status_code == 200:
            return True, "Message sent successfully"
        else:
            return False, f"Failed to send message: {response.text}"

    except Exception as e:
        print(f"Error sending message: {e}", file=sys.stderr)
        return False, f"Error sending message: {str(e)}"

def send_file(recipient: str, media_path: str) -> Tuple[bool, str]:
    """Send a file via WhatsApp."""
    if DEMO_MODE:
        return True, "Demo mode: File would be sent to " + recipient

    try:
        api_url = get_api_url()
        with open(media_path, 'rb') as f:
            files = {'file': f}
            data = {'recipient': recipient}
            response = requests.post(
                f"{api_url}/send-file",
                files=files,
                data=data,
                timeout=30
            )

        if response.status_code == 200:
            return True, "File sent successfully"
        else:
            return False, f"Failed to send file: {response.text}"

    except Exception as e:
        print(f"Error sending file: {e}", file=sys.stderr)
        return False, f"Error sending file: {str(e)}"

def send_audio_message(recipient: str, media_path: str) -> Tuple[bool, str]:
    """Send an audio message as a WhatsApp voice message."""
    if DEMO_MODE:
        return True, "Demo mode: Audio message would be sent to " + recipient

    try:
        api_url = get_api_url()
        with open(media_path, 'rb') as f:
            files = {'file': f}
            data = {'recipient': recipient}
            response = requests.post(
                f"{api_url}/send-audio",
                files=files,
                data=data,
                timeout=30
            )

        if response.status_code == 200:
            return True, "Audio message sent successfully"
        else:
            return False, f"Failed to send audio message: {response.text}"

    except Exception as e:
        print(f"Error sending audio message: {e}", file=sys.stderr)
        return False, f"Error sending audio message: {str(e)}"

def download_media(message_id: str, chat_jid: str) -> Optional[str]:
    """Download media from a WhatsApp message."""
    if DEMO_MODE:
        return "/tmp/demo_media_file.jpg"

    try:
        api_url = get_api_url()
        response = requests.get(
            f"{api_url}/download-media",
            params={"message_id": message_id, "chat_jid": chat_jid},
            timeout=30
        )

        if response.status_code == 200:
            # Save the file
            import uuid
            import tempfile
            filename = f"whatsapp_media_{uuid.uuid4()}"
            filepath = os.path.join(tempfile.gettempdir(), filename)

            with open(filepath, 'wb') as f:
                f.write(response.content)

            return filepath
        else:
            return None

    except Exception as e:
        print(f"Error downloading media: {e}", file=sys.stderr)
        return None