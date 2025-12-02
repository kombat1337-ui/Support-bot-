Telegram Support Bot with AI Integration
A professional Telegram bot for managing technical support tickets with AI-powered assistance, multi-language interface, and forum-based ticket management.

✨ Key Features
Multi-Step Ticket Creation System
7-step process for detailed issue reporting
Media support (photos, videos, documents, voice messages)
Automatic forum topic creation for admin management
Form validation and editing capabilities
AI-Powered Assistance
Integration with Google Gemini AI
Context-aware responses based on ticket history
Professional support agent persona
Automatic logging of AI interactions
Multi-Language Support
Russian, English, and other language options
Dynamic interface translation
User language preference storage
Administrative Tools
Forum-based ticket management in Telegram groups
Automatic log generation and export
Ticket closure with notification system
Manual ticket export commands
Communication Features
Seamless user-admin messaging
Media forwarding between private and group chats
Automatic handling of blocked users
Message history logging
🛠️ Installation & Setup
Prerequisites
Python 3.8 or higher
Telegram Bot Token (from @BotFather)
Google Gemini API Key
Telegram group with forum topics enabled
Installation Steps
1.Clone and navigate to the project directory
2.Install required dependencies
3.full .env



 Available Commands
User Commands
Command	Description	Usage
/start	Welcome message and bot introduction	/start
/newticket	Start creating a new support ticket	/newticket
/ai <question>	Ask AI assistant within active ticket	/ai How do I fix this?
/help <message>	Send feedback to administrators	/help The bot is great!


Admin Commands (in ticket forum topics)
Command	Description	Usage
/close	Close the current ticket	/close
/export_ticket	Export ticket log manually	/export_ticket


🔧 Technical Architecture
Database Schema
users: User language preferences
tickets: Ticket metadata and status
steps: Step-by-step form data
logs: Complete message history

File Structure:
bot2.py                 # Main application file
support.db             # SQLite database
.env                   # Environment variables

Key Components
State Management: FSM for multi-step ticket creation
Media Handling: Support for all Telegram media types
AI Integration: Contextual responses using Gemini
Logging System: Comprehensive activity tracking
Error Handling: Graceful failure recovery

🚀 Deployment
Production Recommendations
Use PostgreSQL instead of SQLite for production
Implement Redis storage for FSM
Add webhook support for better performance
Set up logging with rotation
Configure backups for the database


📊 Ticket Flow
User initiates → /newticket
Language selection → Russian/English/Other
Company/Cheat name → Product identification
7-step form → Detailed problem description
Confirmation → Review and submit
Forum topic created → Admin notification
Communication phase → User-Admin chat
Closure → /close command with logs

🤖 AI Integration Details
Context Building
Ticket metadata (product, user info)
Initial step-by-step form data
Last 15 messages from chat history
Current question context

Prompt Engineering:
Role: Support agent using Gemini
Context: Ticket #{number} for product '{company}'
Task: Provide detailed, professional responses
Language: Match user's language
History: Include previous interactions
Response Formatting
HTML formatting for readability
Professional tone maintenance
Language consistency
Context relevance

🔒 Security Considerations
User Data Protection
No sensitive data storage
Automatic user blocking handling
Ticket isolation
API Security
Environment variable protection
Input validation
Rate limiting consideration
Access Control
Admin-only commands in group context
User-specific ticket access
Thread-based isolation
