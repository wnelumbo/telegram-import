# Import to Telegram as import from WhatsApp
⚡️ This tool can convert Telegram HTML backup to JSON, merge ```messages.json``` files and import back to.
#### What is implemented in Import:
      Messages
      Stickers: static and animated
      Files
      Video
      Round Video Messages
      Voice messages
      Forwarded messages (partially supported)
      Reply (partially supported)
      Locations (partially supported via GoogleMaps)
      Service messages: "Pinned message.." or "The topic has been changed.." (partially supported)
      Calls (partially supported)
      Contacts (partially supported)

#### What is not supported in any meaningful way or due to Telegram's limitations:

      Polls and votes (just as text)
      Text formatting (Bold, Italic, etc.)
      Message reactions (❤️👍 etc.)
      Edited messages
      Custom emoji or premium reactions

<p align="center">
  <table>
    <tr>
      <td align="center">
        <img src="demo/Imported.gif" width="375"/><br>
        <em>Imported</em>
      </td>
      <td align="center">
        <img src="demo/Original.gif" width="390"/><br>
        <em>Original</em>
      </td>
    </tr>
  </table>
</p>

## 🚀 Quick Start
__Insert all scripts into the folder with your chat backup.__
### For ```Converter```
#### 1. Install the required libraries
```pip install beautifulsoup4 pillow mutagen tinytag moviepy```
#### 2. Open the script and insert the names and IDs used in the backup:
    sender_map = {
        "Test #1": "user111111111",  - You
        "Test #2": "user222222222"  - Contact
    }
##### To get the user_id, message the bot at [UserInfoBot](t.me/userinfobot)

##### _To get the user_id of your contact, forward any message from them to the bot._
#### 3. Run the HTML-to-JSON conversion script using the following command:
```python "FOLDER_WHERE_SCRIPT_IS\converter.py" --path "PATH_TO_BACKUP_FOLDER" --chat_id "CONTACT_ID"```

#### _4. Merge (Optional)_
_If you received multiple ```messages.html``` files instead of just one, you need to merge them._

##### Replace the path in the ```merge.py``` script with the location of your "messages.json" files:
    FOLDER = pathlib.Path("YOUR_PATH")
#### _4.1. Run the script using the following command:_
```python "FOLDER_WHERE_SCRIPT_IS\merge.py" --path "FOLDER_WITH_messages.html"```


_After the conversion is complete, rename the ```messages.json``` file to ```result.json```._

_If you combined files after conversion, the merged file does not need renaming._


### For ```Import```
___Before importing a full backup, it's best to test everything on a small conversation.____
#### 1. Install the required libraries
```pip install telethon tqdm python-dateutil```
#### 2. Before running the import, insert your ```api_id``` and ```api_hash``` into the script.
    api_id, api_hash = ID, 'HASH'
##### To ```api_id``` and ```api_hash```, log in to [My Telegram website](https://my.telegram.org) and create a test application.
#### 3. Run ```import.py``` with the following command:
```python "FOLDER_WHERE_SCRIPT_IS\import.py" --path "FOLDER_WHERE_RESULT_IS\result.json" --peer "@USERNAME"```

_Then, you will go through the authentication process, including 2FA (if enabled). After that, the import begins._

_Messages will appear in the chat after the last file is uploaded._

# Important:
#### 1. When entering 2FA, the password will not be shown in the console. Type it and press Enter.
#### 2. You and your contact must be in each other's contacts for the import process to succeed without errors.
#### 3. Large backups are best imported at night. I tested all the scripts on a conversation with 130,000 messages — 16,000 of which were files and the process took me 6 hours.
