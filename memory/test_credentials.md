# CrusaderBot Test Credentials

## Telegram Bot
Token: 8795145097:AAGQW9yIOswG3GMmvTByfLpHPnLWU08DOk8

## Admin Identity
Operator Chat ID: 5642722297
Admin check: telegram_user_id == OPERATOR_CHAT_ID OR user_tiers.tier = 'ADMIN'

## Local PostgreSQL
DATABASE_URL: postgresql://postgres:crusader123@localhost:5432/crusaderbot

## APIs
HEISENBERG_API_TOKEN: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
ALCHEMY_POLYGON_RPC: https://polygon-mainnet.g.alchemy.com/v2/kp6pwdRDVIL-rP-7oR9S-

## Test User Flow (Concierge Onboarding)
1. /start → Welcome card → tap [🚀 Get Started]
2. Wallet Init → $1,000 credited → tap [Continue →]
3. Risk Profile → choose strategy
4. Done → Dashboard V5 with state-driven keyboard

## Bot Commands
/start  - Start or reset onboarding
/help   - Show help
/menu   - Show persistent keyboard
/admin  - Admin panel (operator only)
