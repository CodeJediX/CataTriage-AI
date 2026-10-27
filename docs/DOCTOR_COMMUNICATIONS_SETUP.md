# Doctor accounts and communication

## Current email method

Doctor setup and recovery emails use Firebase Authentication in the isolated `catatriage-ai-mail-39` project. This project is on the free Spark plan; billing was checked and is disabled. The database and clinical images remain in the existing private Supabase schemas.

New doctors receive a secure password-setup link, rather than a plaintext password. They choose a password in Firebase's hosted handler, then use Continue to return to the doctor portal with their username filled in. If Firebase requires address verification, the portal sends a verification email and asks the doctor to complete it before signing in. The default Firebase sender is used; a Gmail app password and custom email domain are unnecessary.

Only active, admin-registered doctors who have been invited through the app may link their Firebase email identity. The server checks email verification and the registered address. Creating a Firebase user alone grants no application access. On successful setup/sign-in the app synchronizes its salted password hash, clears the setup requirement and revokes older application sessions. Linked accounts authenticate with Firebase, and the Change password form updates both stores. Existing non-linked logins stay usable until setup is completed.

The server-only `FIREBASE_WEB_API_KEY` is set in Vercel. Local configuration uses `FIREBASE_MAIL_CONFIG_FILE` pointing to the private `data/.secrets/firebase_mail.json`. Administrative Google OAuth credentials are never deployed. Firebase's documented free limit is 150 password-reset emails/day; verify current quotas before changing usage. Acceptance is shown honestly; it does not guarantee Inbox delivery. Check Spam when needed.

The optional Gmail implementation remains available if Firebase is not configured, using Gmail OAuth or an app password. No paid email provider, Resend installation, domain purchase or billing upgrade was made. Supabase's default email sender was not used because it restricts recipients to project team members.

## Account management

Open **Hospital dashboard → Manage accounts**. Admins can edit patient demographics, contact information and doctor assignment, and edit doctor names, email addresses, telephone numbers and working schedules. Usernames are stable identifiers. Existing clinical approvals are preserved. Transfers are rejected if the new doctor cannot cover an existing future booking.

Delete is reversible: the record leaves active views and can be restored in Deleted records. Deleting a patient cancels future confirmed surgeries and removes future consultation bookings, retaining the booking snapshot, medical history and audit trail. Restoration does not reinstate cancelled bookings automatically. Deleting a doctor revokes sign-in sessions; active patients must first be transferred to an available doctor. Restoration preserves the patient transfers and requires a fresh sign-in. No existing production accounts were deleted during implementation.

## Messages and surgery notices

The doctor's Inbox/Sent folders support internal admin announcements, leave notices, messages to other doctors and messages in the history of assigned patients. Only recipients can mark messages read. Existing patient WhatsApp delivery remains in the patient communication form.

Final surgery confirmation saves an exact snapshot of the requested Surgery Appointment Confirmation template and opens a calendar pop-up. Duplicate submissions do not send twice. Automatic WhatsApp still needs a matching verified Business sender, access token, phone-number ID, supported Graph API version and approved template. Without them, the message is stored not sent, with a free manual Open WhatsApp link. No WhatsApp billing was activated.

## Sign-in identity

The supplied CataTriage AI image is the main logo and favicon. The sign-in pages use a CSS 3D optical background and floating logo, with a pause button and reduced-motion support. The requested Education demo/Supabase notice is hidden on sign-in; model-result pages retain their research limitations.

## Schema additions

Apply the base schemas, then each schema addition once: `doctor_communications.sql`, `account_management.sql` and `firebase_mail.sql`, under `deployment/cloud/`. Tables are private, use RLS and deny public/anon/authenticated access. Admin profile mutations span the hospital and doctor schemas in one Postgres transaction. Local SQLite uses an attached doctor database for the same atomic changes.

References: [Firebase email limits](https://firebase.google.com/docs/auth/limits), [Firebase Auth REST API](https://firebase.google.com/docs/reference/rest/auth), [Supabase SMTP restrictions](https://supabase.com/docs/guides/auth/auth-smtp).
