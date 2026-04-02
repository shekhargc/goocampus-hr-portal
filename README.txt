GooCampus Leave Management Dashboard
=====================================
FY 2026-2027

SETUP (one-time)
----------------
1. Make sure Python 3.8+ is installed on your system
2. Open Terminal / Command Prompt
3. Navigate to this folder:
      cd goocampus-leave-dashboard
4. Install Flask:
      pip install flask
5. Run the app:
      python app.py

ACCESS
------
- On your machine:  http://localhost:5000
- From other devices on your network:  http://<YOUR-LOCAL-IP>:5000
  (Find your IP: run 'ipconfig' on Windows or 'ifconfig' on Mac/Linux)

LOGIN CREDENTIALS
-----------------
Admin:
  Code: admin
  Password: goocampus2026

Employees (default):
  Code: <first name lowercase> (e.g. deepak, harish, robin)
  Password: same as code
  (Employees should change their password on first login)

LEAVE POLICY (FY 2026-27)
--------------------------
- Annual Leave: 15 days/year (accrues at 1.25 days/month)
- Sick Leave: 5 days/year (available fully from April 1)
- Casual Leave: 5 days/year (available fully from April 1)
- Carry Forward from FY 2025-26 is added to Annual Leave

FEATURES
--------
- Admin dashboard: view all team balances at a glance
- Add leave: single entry with live balance preview
- Bulk entry: add leave for multiple employees on same date
- Employee view: each person sees their own balance + history
- Manage team: add/remove employees, update carry-forward
- Auto-calculation: annual leave accrues monthly, no manual rollover needed

NOTE
----
The database file (leave_manager.db) stores all data locally.
Back it up regularly (just copy the file).
To reset everything, delete leave_manager.db and run:
    python seed_data.py
