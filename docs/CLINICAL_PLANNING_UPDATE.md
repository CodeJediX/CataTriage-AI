# Clinical planning and eye upload rounds

The doctor review page saves **Reported symptoms** and **Clinical notes** when the doctor requests a surgery-date suggestion. It does not start another image-upload round. The assigned doctor is checked before any update.

The date assistant receives an allowlisted structured summary from both fields, the current round's eye findings, the approved tier, waiting time, and available doctor/theatre/bed candidates. Patient names, contact details, case identifiers and raw free text are excluded from that request. Explicit `not before YYYY-MM-DD` or `earliest surgery date: YYYY-MM-DD` constraints restrict the candidate window.

Gemma remains the first model. The configured free NVIDIA model is tried when eligible provider failures occur. The interface identifies the model that actually responded and labels local availability rules if neither model responds. AI dates must match an available candidate; the model can instead request clinical assessment. A suggestion never creates a surgery booking.

The separate clinical advice box shows review points, recognised evidence from each input, missing information, provider attribution, limitations and links to NICE, NEI and NHS guidance. Acute visual warning features and a recorded refusal of surgery pause elective date suggestions. Pending preoperative work remains flagged. These checks use keywords and can miss context; they are review aids, not a diagnosis or surgical clearance. The exact best medical surgery date is not validated by this system.

Fixed 2/7/14-day delays were removed: local workflow tiers do not establish medically safe waiting periods. The clinician must review the original text, examination, patient wishes and preoperative assessment before confirming timing.

The case workspace shows only images carrying the current upload-round identifier. Earlier genuine uploads stay in a separate history section. It never fills an empty eye field with a past upload. A round with no images has no active image analysis. Legacy images without a round identifier are shown one at a time rather than combined across visits. Fresh cloud seeding excludes image records and attachments.

Five agent verification uploads were removed from the cloud database after an exact identifier/batch check. The user's current left/right images were preserved. A private recovery copy remains outside the deployment repository.

Validation: the 63-test regression suite passed, followed by the additional pending-biometry check and targeted round-isolation/form checks. A live provider request with fictional data returned a validated candidate date and clinical considerations through the free fallback. Production release commit: `e82b4e68b797751f2c34bb379261a750445ae39e`.
