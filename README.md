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

7. Locate the `Manifest.db` file inside your backup folder. This database tracks files in the backup. It should be at:  
   `~/iphone_backup/Manifest.db`

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

