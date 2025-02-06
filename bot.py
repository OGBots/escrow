import logging
from datetime import datetime
import random
import string
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class Config:
    ADMIN_IDS = [6459253633]  # Replace with your Telegram ID
    ESCROW_FEE = 0.03    # 3%
    UPI_ID = "devansh269@fam"  # Replace with your UPI ID
    MIN_AMOUNT = 100     # Minimum transaction amount
    
    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in Config.ADMIN_IDS

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('escrow_bot.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        c = self.conn.cursor()
        
        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users
                    (user_id INTEGER PRIMARY KEY,
                     username TEXT,
                     balance REAL DEFAULT 0,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Transactions table (for deposits and withdrawals)
        c.execute('''CREATE TABLE IF NOT EXISTS transactions
                    (tx_id TEXT PRIMARY KEY,
                     user_id INTEGER,
                     type TEXT,
                     amount REAL,
                     status TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     FOREIGN KEY (user_id) REFERENCES users (user_id))''')
        
        # Escrow deals table
        c.execute('''CREATE TABLE IF NOT EXISTS deals
                    (deal_id TEXT PRIMARY KEY,
                     creator_id INTEGER,
                     counterparty_id INTEGER,
                     amount REAL,
                     status TEXT,
                     description TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     FOREIGN KEY (creator_id) REFERENCES users (user_id),
                     FOREIGN KEY (counterparty_id) REFERENCES users (user_id))''')
        
        self.conn.commit()

class Messages:
    WELCOME = """
🔒 Welcome to the Escrow Bot!

Available commands:
/balance - Check your balance
/deposit - Request to add funds
/withdraw - Request to withdraw funds
/create_deal - Create new escrow deal
/my_deals - View your deals
/help - Show this help message
"""

    ADMIN_HELP = """
👑 Admin Commands:
/verify_tx [tx_id] [approve/reject] [amount] - Verify transaction
/admin_deals - View all deals
/resolve_deal [deal_id] [approve/reject] - Resolve deal
"""

class EscrowBot:
    def __init__(self):
        self.db = Database()
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        c = self.db.conn.cursor()
        c.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)',
                 (user_id, username))
        self.db.conn.commit()
        
        welcome_text = Messages.WELCOME
        if Config.is_admin(user_id):
            welcome_text += "\n" + Messages.ADMIN_HELP
            
        await update.message.reply_text(welcome_text)
    
    async def check_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        c = self.db.conn.cursor()
        c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        
        if result:
            balance = result[0]
            await update.message.reply_text(f"Your current balance: ₹{balance:.2f}")
        else:
            await update.message.reply_text("Error fetching balance. Please try /start first.")
    
    async def request_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        tx_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        c = self.db.conn.cursor()
        c.execute('''INSERT INTO transactions (tx_id, user_id, type, amount, status)
                    VALUES (?, ?, ?, ?, ?)''',
                 (tx_id, user_id, 'DEPOSIT', 0, 'PENDING'))
        self.db.conn.commit()
        
        message = (
            f"📥 Deposit Request\n\n"
            f"Transaction ID: {tx_id}\n"
            f"UPI ID: {Config.UPI_ID}\n\n"
            f"1. Send money to the above UPI ID\n"
            f"2. Use the Transaction ID as reference\n"
            f"3. Send the screenshot to admin\n"
            f"4. Wait for admin verification"
        )
        await update.message.reply_text(message)
        
        # Notify admin
        for admin_id in Config.ADMIN_IDS:
            admin_message = (
                f"New deposit request!\n\n"
                f"User: @{username}\n"
                f"Transaction ID: {tx_id}"
            )
            try:
                await context.bot.send_message(admin_id, admin_message)
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    async def request_withdrawal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text(
                "Please specify the amount to withdraw.\n"
                "Usage: /withdraw <amount>"
            )
            return
        
        try:
            amount = float(context.args[0])
            if amount < Config.MIN_AMOUNT:
                await update.message.reply_text(f"Minimum withdrawal amount is ₹{Config.MIN_AMOUNT}")
                return
                
            user_id = update.effective_user.id
            username = update.effective_user.username
            
            c = self.db.conn.cursor()
            c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            current_balance = c.fetchone()[0]
            
            if current_balance < amount:
                await update.message.reply_text("Insufficient balance!")
                return
            
            tx_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            c.execute('''INSERT INTO transactions (tx_id, user_id, type, amount, status)
                        VALUES (?, ?, ?, ?, ?)''',
                     (tx_id, user_id, 'WITHDRAWAL', amount, 'PENDING'))
            self.db.conn.commit()
            
            await update.message.reply_text(
                f"Withdrawal request submitted!\n"
                f"Amount: ₹{amount:.2f}\n"
                f"Transaction ID: {tx_id}\n\n"
                "Please wait for admin approval."
            )
            
            # Notify admin
            for admin_id in Config.ADMIN_IDS:
                admin_message = (
                    f"New withdrawal request!\n\n"
                    f"User: @{username}\n"
                    f"Amount: ₹{amount:.2f}\n"
                    f"Transaction ID: {tx_id}"
                )
                try:
                    await context.bot.send_message(admin_id, admin_message)
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
                    
        except ValueError:
            await update.message.reply_text("Please enter a valid amount.")

    async def create_deal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not context.args or len(context.args) < 3:
            await update.message.reply_text(
                "Usage: /create_deal <amount> <@username> <description>"
            )
            return
        
        try:
            amount = float(context.args[0])
            counterparty = context.args[1]
            description = ' '.join(context.args[2:])
            
            if amount < Config.MIN_AMOUNT:
                await update.message.reply_text(f"Minimum deal amount is ₹{Config.MIN_AMOUNT}")
                return
            
            # Check balance
            c = self.db.conn.cursor()
            c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            current_balance = c.fetchone()[0]
            
            if current_balance < amount:
                await update.message.reply_text("Insufficient balance!")
                return
            
            # Generate deal ID
            deal_id = 'DEAL-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            
            # Create deal
            c.execute('''INSERT INTO deals 
                        (deal_id, creator_id, counterparty_id, amount, status, description)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                     (deal_id, user_id, counterparty, amount, 'PENDING', description))
            
            # Lock the amount
            c.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?',
                     (amount, user_id))
            
            self.db.conn.commit()
            
            await update.message.reply_text(
                f"Escrow deal created!\n"
                f"Deal ID: {deal_id}\n"
                f"Amount: ₹{amount:.2f}\n"
                f"Counterparty: {counterparty}\n"
                f"Description: {description}\n\n"
                f"Waiting for counterparty to accept..."
            )
            
        except ValueError:
            await update.message.reply_text("Please enter a valid amount.")

    async def my_deals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        c = self.db.conn.cursor()
        c.execute('''SELECT * FROM deals 
                    WHERE creator_id = ? OR counterparty_id = ?
                    ORDER BY created_at DESC''',
                 (user_id, user_id))
        deals = c.fetchall()
        
        if not deals:
            await update.message.reply_text("You don't have any deals yet.")
            return
        
        message = "Your deals:\n\n"
        for deal in deals:
            message += (
                f"Deal ID: {deal[0]}\n"
                f"Amount: ₹{deal[3]:.2f}\n"
                f"Status: {deal[4]}\n"
                f"Description: {deal[5]}\n"
                f"Created: {deal[6]}\n\n"
            )
        
        await update.message.reply_text(message)

    async def admin_verify_transaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not Config.is_admin(update.effective_user.id):
            return
        
        if len(context.args) < 3:
            await update.message.reply_text(
                "Usage: /verify_tx <tx_id> <approve/reject> <amount>"
            )
            return
        
        tx_id = context.args[0]
        action = context.args[1].lower()
        
        if action not in ['approve', 'reject']:
            await update.message.reply_text("Invalid action. Use 'approve' or 'reject'")
            return
        
        c = self.db.conn.cursor()
        c.execute('SELECT * FROM transactions WHERE tx_id = ?', (tx_id,))
        tx = c.fetchone()
        
        if not tx:
            await update.message.reply_text("Transaction not found!")
            return
        
        if action == 'approve':
            try:
                amount = float(context.args[2])
                
                c.execute('UPDATE transactions SET status = ?, amount = ? WHERE tx_id = ?',
                         ('COMPLETED', amount, tx_id))
                
                if tx[2] == 'DEPOSIT':
                    c.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?',
                             (amount, tx[1]))
                elif tx[2] == 'WITHDRAWAL':
                    c.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?',
                             (amount, tx[1]))
                
                self.db.conn.commit()
                
                await context.bot.send_message(
                    tx[1],
                    f"Your {tx[2].lower()} of ₹{amount:.2f} has been approved!\n"
                    f"Transaction ID: {tx_id}"
                )
                
                await update.message.reply_text("Transaction approved successfully!")
                
            except ValueError:
                await update.message.reply_text("Please enter a valid amount.")
        else:
            c.execute('UPDATE transactions SET status = ? WHERE tx_id = ?',
                     ('REJECTED', tx_id))
            self.db.conn.commit()
            
            await context.bot.send_message(
                tx[1],
                f"Your {tx[2].lower()} request has been rejected.\n"
                f"Transaction ID: {tx_id}"
            )
            
            await update.message.reply_text("Transaction rejected!")

    async def admin_resolve_deal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not Config.is_admin(update.effective_user.id):
            return
        
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /resolve_deal <deal_id> <approve/reject>"
            )
            return
        
        deal_id = context.args[0]
        action = context.args[1].lower()
        
        if action not in ['approve', 'reject']:
            await update.message.reply_text("Invalid action. Use 'approve' or 'reject'")
            return
        
        c = self.db.conn.cursor()
        c.execute('SELECT * FROM deals WHERE deal_id = ?', (deal_id,))
        deal = c.fetchone()
        
        if not deal:
            await update.message.reply_text("Deal not found!")
            return
        
        if action == 'approve':
            # Transfer funds to counterparty
            c.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?',
                     (deal[3], deal[2]))  # amount to counterparty
            
            c.execute('UPDATE deals SET status = ? WHERE deal_id = ?',
                     ('COMPLETED', deal_id))
            
            self.db.conn.commit()
            
            # Notify both parties
            await context.bot.send_message(
                deal[1],  # creator
                f"Deal {deal_id} has been completed. Funds released to counterparty."
            )
            await context.bot.send_message(
                deal[2],  # counterparty
                f"Deal {deal_id} has been completed. Funds received: ₹{deal[3]:.2f}"
            )
            
        else:
            # Return funds to creator
            c.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?',
                     (deal[3], deal[1]))
            
            c.execute('UPDATE deals SET status = ? WHERE deal_id = ?',
                     ('REJECTED', deal_id))
            
            self.db.conn.commit()
            
            # Notify both parties
            await context.bot.send_message(
                deal[1],  # creator
                f"Deal {deal_id} has been cancelled. Funds returned to your balance."
            )
            await context.bot.send_message(
                deal[2],  # counterparty
                f"Deal {deal_id} has been cancelled."
            )
        
        await update.message.reply_text(f"Deal {deal_id} has been {action}d!")

def main():
    # Initialize bot
    bot = EscrowBot()
    
    # Create application
    application = Application.builder().token('7806389764:AAFEyK16Otkex4lwUMVsmdA_HpWS729_fxM').build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.start))
    application.add_handler(CommandHandler("balance", bot.check_balance))
    application.add_handler(CommandHandler("deposit", bot.request_deposit))
    application.add_handler(CommandHandler("withdraw", bot.request_withdrawal))
    application.add_handler(CommandHandler("create_deal", bot.create_deal))
    application.add_handler(CommandHandler("my_deals", bot.my_deals))
    application.add_handler(CommandHandler("verify_tx", bot.admin_verify_transaction))
    application.add_handler(CommandHandler("resolve_deal", bot.admin_resolve_deal))
    
    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()
