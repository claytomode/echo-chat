* WIP AI chat that uses your phone's messages as memory

## Vector Store

To create the vector store, you must have the `sms.db` SQLite database.

You can obtain this from a backup of your iPhone. There are many ways to do this depending on your operating system. There are lots of services to do this. A lot look very sketchy and some cost money. You **do not** need a paid solution.  
This is what I did. This can serve as a rough guide.

**If you do not have an iPhone, you may have to do database transformations to create this file.**

I used [libimobiledevice](https://github.com/libimobiledevice/libimobiledevice) to back up my phone and extract `sms.db` using the following steps:

1. Plug in your phone and select 'Trust this Computer'. (this may pop up multiple times)

2. Create a mount point directory for your iPhone  
   ``` bash
   mkdir ~/iPhone
   ```

3. Mount your iPhone's filesystem  
   ``` bash
   ifuse ~/iPhone
   ```

4. Verify your phone is connected and trusted  
   ``` bash
   ideviceinfo
   ```

5. Create a directory to hold your backup  
   ``` bash
   mkdir ~/iphone_backup
   ```

6. Create a full backup of your iPhone (this may take several minutes)  
   ``` bash
   idevicebackup2 backup ~/iphone_backup
   ```

7. Locate the `Manifest.db` file inside your backup folder. This database tracks file locations in the backup.

8. Query `Manifest.db` to find the fileID and relative path of `sms.db`  
   ``` bash
   sqlite3 ~/iphone_backup/Manifest.db "SELECT fileID, relativePath FROM Files WHERE relativePath LIKE '%sms.db';"
   ```

   This will output something like:  
   `3d/3db6f8d12a06e8b0f21357cfbb85efbb2dd01234 sms.db`

9. Copy the actual `sms.db` file to your home directory, using the fileID and subfolder:  
   ``` bash
   cp ~/iphone_backup/3d/3db6f8d12a06e8b0f21357cfbb85efbb2dd01234 ~/sms.db
   ```

10. Open and query the SMS database!
    ``` bash
    sqlite3 ~/sms.db
    ```
    
    ``` sql
    SELECT
      datetime(date / 1000000000 + strftime('%s','2001-01-01'), 'unixepoch', 'localtime') AS timestamp,
      text
    FROM
      message
    WHERE
      is_from_me = 1 AND text IS NOT NULL
    ORDER BY
      date ASC
    LIMIT 1;
    ```

    Example output:  
    ```
    2020-08-13 17:26:09|Ok
    ```

    This shows the first text message you sent that’s still saved.

11. You now have a full database of your iPhone texts! This can be used to create the vector store. Feel free to remove your backup directory as you no longer need it.

## SMS Database Transformations for Non-iPhone Sources

The provided Python utility is designed to work with an `sms.db` file that closely resembles the schema found on iOS devices. If your SMS data comes from an Android phone, a different mobile platform, or a custom export, you will likely need to perform some database transformations to make it compatible.

### Required `sms.db` Schema

To ensure compatibility with the utility, your SQLite `sms.db` file must contain the following tables and columns:

1.  **`message` table**:
    * `ROWID`: A unique integer identifier for each message.
    * `text`: The content of the message (TEXT).
    * `is_from_me`: An integer (INTEGER) where `0` indicates an incoming message and `1` indicates an outgoing message.
    * `date`: A timestamp (INTEGER), preferably in Unix epoch seconds, or a consistent integer value that allows for accurate chronological sorting.

2.  **`handle` table**:
    * `ROWID`: A unique integer identifier for each handle (contact).
    * `id`: The contact's identifier (TEXT), such as a phone number (e.g., `+15551234567`) or an email address.

3.  **Relationship**:
    * The `message.handle_id` column must be an integer that links to the `handle.ROWID` of the corresponding contact.

**Example SQL to create the required tables:**

```sql
CREATE TABLE handle (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL
);

CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    is_from_me INTEGER NOT NULL, -- 0 for incoming, 1 for outgoing
    date INTEGER,               -- Unix epoch seconds (or other consistent sortable integer)
    handle_id INTEGER,
    FOREIGN KEY (handle_id) REFERENCES handle(ROWID)
);
```

### How to Transform Your Data

You will need to export your SMS data from its original source (e.g., using an Android SMS backup app, or a custom script) and then write your own script (e.g., in Python) to read this exported data and insert it into an SQLite database that conforms to the schema described above.

Once you have your transformed `sms.db` file created with the correct schema and populated data, you can then use this file as the `sms_db_path` parameter in the `create_qdrant_sms_store` function.
