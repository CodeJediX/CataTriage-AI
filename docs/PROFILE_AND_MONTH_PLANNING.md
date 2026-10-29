# Doctor profiles and month-based surgery planning

Doctor profiles on the website and Android 1.1.0 support changing the photo and sign-in username, plus a secure password-change link. Username changes require the current password and revoke existing sessions. Immutable account IDs preserve patient assignments, messages, Firebase email identity and audit history. New sign-in names cannot collide with any existing account or active alias. Firebase setup emails use the current sign-in name.

The workflow is: independent doctor priority review → recorded functional impact/progression/preference → AI month proposal with reasons → explicit doctor month approval → admin calendar/AI free-slot suggestion → admin confirmation. The doctor proposal contains a month, with no exact proposed date. Existing confirmed appointments remain visible as historical or scheduled records.

Operational proposal windows are illustrative, not clinically validated waiting periods. Mild, stable, Tier 3 cases with a doctor-recorded preference for later planning start with month candidates three months ahead; other assessed cases use the earlier planning window indicated by impact, progression and doctor priority. The doctor may choose another suitable month within the next 12 months after review. The image classifier's confidence does not influence postponement. Acute warning symptoms or recorded surgery refusal pause elective planning. Unknown impact/progression or absent doctor priority requires assessment first.

Gemma remains the configured primary AI. Only configured free OpenRouter models are eligible; the existing free NVIDIA fallback is available when the primary endpoint fails. The AI receives recognised clinical features and availability summaries, without patient names, contact information or raw notes. Candidate values and explanations are validated. Local planning explanations remain available if providers fail.

Month approval records the doctor, reason, assessment and an evidence hash. Changes to symptoms, notes, imaging, clinical review, medical history or assigned doctor invalidate the handoff. Booking rechecks the approved month and current evidence. Clinical writes and scheduling share the database transaction lock. Admins cannot change the month or priority. Slots check working hours, leave, existing doctor appointments, theatre limits and bed capacity. The 30-minute grid is a local scheduling convention and is not an estimate of surgery duration.

Apply `deployment/cloud/profile_month_planning.sql` after the existing cloud schemas before deploying this version. It adds two private RLS-protected tables, with access limited to the existing server role. No existing patient records or bookings are migrated into an approved month automatically.

Release APK: `output/android/CataTriage-Doctor-1.1.0.apk`. It uses the same signing key and package as 1.0.0, with versionCode 2. Existing users can install it as an update. The server rejects final-date booking from the older doctor APK; users should update to see the month workflow.

Verification uses isolated records for changes and read-only checks in production. No live profile, clinical note, month approval, surgery booking or patient notification is changed as part of verification.
