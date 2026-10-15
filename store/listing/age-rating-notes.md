# Age rating (IARC questionnaire): suggested answers

Partner Center → your app → **Age ratings**. The questionnaire is run by IARC and gives you ratings for every region (ESRB, PEGI, USK, and so on) at once. Answer for what Dr. Doc actually is: an offline file utility.

| Question (wording varies slightly) | Answer | Why |
|---|---|---|
| App category | **Utility, Productivity, Communication or Reference** ("not a game") | It's a file converter/editor |
| Violence, blood, gore | No | None |
| Fear / horror | No | The ghost-like mascot is cute, not scary |
| Sexuality / nudity | No | None |
| Crude humour / language / profanity | No | None |
| Controlled substances (drugs, alcohol, tobacco) | No | None |
| Gambling / simulated gambling | No | None |
| **Does the app allow users to interact or exchange content with other users?** | **No** | No chat, no accounts, no sharing, no network |
| **Does the app share the user's current physical location with other users?** | **No** | No location access |
| **Does the app allow purchases of digital goods?** | **No** (unless you add in-app purchases) | |
| **Does the app contain unrestricted internet access (e.g. a browser)?** | **No** | The WebView only shows the app's own local UI. Links don't open arbitrary web content inside the app. |
| Does the app collect personal information / share with third parties? | No | See the privacy policy |
| Does the app display user-generated content? | No (only the user's own local files) | |

**Expected result:** IARC 3+, ESRB Everyone, PEGI 3, USK 0 or similar.

Tip: if a question asks whether the app "lets users view content from the internet", answer **No**. Dr. Doc never loads remote pages. Its window only shows `http://127.0.0.1` (the app itself).
