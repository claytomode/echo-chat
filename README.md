##  Vector Store
To create the vectore store, you must have the `sms.db` SQLite database. 

You can obtain this from a backup of your iPhone. There are many ways to do this depending on your operating system. There are lots of services to do this. A lot look very sketchy and some cost money. You **do not** need a paid solution.
This is what I did. This can serve as a rough guide.

**If you do not have an iPhone, you may have to do database transformations to create this file.**

I used [libimobiledevice](https://github.com/libimobiledevice/libimobiledevice) to backup my phone and extract `sms.db` using the following steps:

1. Plug in your phone and select 'Trust this Computer'. (this may pop up multiple times)
2. Create a directory to mount your iPhone
   ```bash
   mkdir ~/iPhone
   ```
3. Mount your iPhone
   ```bash
   ifuse ~/iPhone
   ```
4. Ensure your phone is properly mounted
   ```bash
   ideviceinfo
   ```
5. Create a directory for the backup
   ```bash
   mkdir ~/iphone_backup
   ```
6. Create a backup. This may take a while.
   ```bash
   idevicebackup2 backup ~/iphone_backup
   ```
7. Locate the `Manifest.db` file in the backup.
8. Query this database to find the location of `sms.db`
   ```bash
   sqlite3 Manifest.db "SELECT fileID, relativePath FROM Files WHERE relativePath LIKE '%sms.db';
   ```
9. Copy this file into its own directory
    ```bash
    cp {FILE LOCATION FROM STEP 8} ~/sms.db
    ```
10. Query the database!
    ```bash
    sqlite3 ~/sms.db
    ```
    ```sql
    SELECT
    datetime(date / 1000000000 + strftime('%s','2001-01-01'), 'unixepoch', 'localtime') AS timestamp, text
    FROM
      message
    WHERE
      is_from_me = 1 AND text IS NOT NULL
    ORDER BY
      date ASC
    LIMIT 1;
    ```
    This should show you the first text you have sent (that is still saved)!
11. You now have a database of all your texts!! From here, feel free to delete the backup directory.
