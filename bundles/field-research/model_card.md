# Field research email-header model

- Version: 0.3.1-precision-field
- Status: experimental, not production approved
- ONNX model copied from the project's 0.3.1-precision research bundle
- Training source: SpamAssassin headers, not confirmed Microsoft 365 compromises
- Excludes message body, subject, preview, and attachment bytes
- Use: inspect email-header probability during an authorized pilot, not autonomous blocking
- User risk score: separate canonical signal fusion, not a trained user-compromise model
- A high score is an analyst-review hypothesis, not proof of account compromise
