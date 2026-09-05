"""
Payment Degradation Data Generator - Version 2
Now uses REAL Razorpay error codes for realistic synthetic data
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import json
from razorpay_error_mapping import (
    RAZORPAY_ERROR_MAPPING,
    get_error_category,
    get_recovery_strategy,
    is_common_error,
    get_common_errors_by_category
)

# Set seed for reproducibility
np.random.seed(42)
random.seed(42)

class PaymentDegradationGeneratorV2:
    def __init__(self):
        self.merchant_id = "m_test_123456"
        self.transactions = []
        self.transaction_counter = 0
        self.payment_methods = ['card', 'upi', 'netbanking', 'wallet']
        self.common_errors = get_common_errors_by_category()
        
    def create_transaction(self, amount, status, method, error_code=None, retry_count=0, timestamp=None):
        """Create a single transaction record with real Razorpay error codes"""
        self.transaction_counter += 1
        
        if timestamp is None:
            timestamp = datetime.now()
        
        root_cause = get_error_category(error_code) if error_code else None
        recovery_strategy = get_recovery_strategy(error_code) if error_code else None
        
        txn = {
            'transaction_id': f'txn_{self.transaction_counter:06d}',
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'date': timestamp.strftime('%Y-%m-%d'),
            'hour': timestamp.strftime('%H'),
            'merchant_id': self.merchant_id,
            'customer_id': f'cust_{random.randint(1000, 9999)}',
            'amount': amount,
            'currency': 'INR',
            'payment_method': method,
            'status': status,
            'error_code': error_code,  # Real Razorpay error code
            'root_cause': root_cause,
            'recovery_strategy': recovery_strategy,
            'retry_count': retry_count,
            'subscription_id': None,
            'merchant_config': {
                'gateway_version': 'v2.1',
                'retry_enabled': True,
                'max_retries': 3
            }
        }
        
        self.transactions.append(txn)
        return txn
    
    def generate_baseline_day(self, date, num_transactions=150):
        """
        Normal day: 95% success, random failures
        """
        print(f"Generating Baseline Day: {date.strftime('%Y-%m-%d')} (95% success)")
        
        # Success transactions
        num_success = int(num_transactions * 0.95)
        for i in range(num_success):
            timestamp = date + timedelta(minutes=i*10)
            self.create_transaction(
                amount=random.randint(1000, 10000),
                status='success',
                method=random.choice(self.payment_methods),
                error_code=None,
                timestamp=timestamp
            )
        
        # Failed transactions - random mix from all categories
        num_failed = num_transactions - num_success
        all_common_errors = (
            self.common_errors['CUSTOMER_SIDE'] +
            self.common_errors['SYSTEM_SIDE'] +
            self.common_errors['MERCHANT_SIDE']
        )
        
        for i in range(num_failed):
            timestamp = date + timedelta(minutes=(num_success + i)*10)
            error_code = random.choice(all_common_errors)
            self.create_transaction(
                amount=random.randint(1000, 10000),
                status='failed',
                method=random.choice(self.payment_methods),
                error_code=error_code,
                timestamp=timestamp
            )
        
        print(f"  ✓ Created {num_success} successful + {num_failed} failed (random mix)")
    
    def generate_customer_degradation(self, date, num_transactions=150):
        """
        CUSTOMER-SIDE degradation: 78% success
        80% of failures are customer-side issues
        """
        print(f"Generating Customer-Side Degradation: {date.strftime('%Y-%m-%d')} (78% success)")
        
        num_success = int(num_transactions * 0.78)
        for i in range(num_success):
            timestamp = date + timedelta(minutes=i*10)
            self.create_transaction(
                amount=random.randint(1000, 10000),
                status='success',
                method=random.choice(self.payment_methods),
                error_code=None,
                timestamp=timestamp
            )
        
        # Failed transactions
        num_failed = num_transactions - num_success
        customer_errors = self.common_errors['CUSTOMER_SIDE']
        system_errors = self.common_errors['SYSTEM_SIDE']
        
        for i in range(num_failed):
            timestamp = date + timedelta(minutes=(num_success + i)*10)
            # 80% customer-side, 20% system-side
            if random.random() < 0.8:
                error_code = random.choice(customer_errors)
            else:
                error_code = random.choice(system_errors)
            
            self.create_transaction(
                amount=random.randint(1000, 10000),
                status='failed',
                method=random.choice(self.payment_methods),
                error_code=error_code,
                timestamp=timestamp
            )
        
        print(f"  ✓ Created {num_success} successful + {num_failed} failed (80% customer-side)")
    
    def generate_system_degradation(self, date, num_transactions=150):
        """
        SYSTEM-SIDE degradation: 80% success
        75% of failures are system-side issues
        """
        print(f"Generating System-Side Degradation: {date.strftime('%Y-%m-%d')} (80% success)")
        
        num_success = int(num_transactions * 0.80)
        for i in range(num_success):
            timestamp = date + timedelta(minutes=i*10)
            self.create_transaction(
                amount=random.randint(1000, 10000),
                status='success',
                method=random.choice(self.payment_methods),
                error_code=None,
                timestamp=timestamp
            )
        
        # Failed transactions
        num_failed = num_transactions - num_success
        system_errors = self.common_errors['SYSTEM_SIDE']
        customer_errors = self.common_errors['CUSTOMER_SIDE']
        
        for i in range(num_failed):
            timestamp = date + timedelta(minutes=(num_success + i)*10)
            # 75% system-side, 25% customer-side
            if random.random() < 0.75:
                error_code = random.choice(system_errors)
            else:
                error_code = random.choice(customer_errors)
            
            self.create_transaction(
                amount=random.randint(1000, 10000),
                status='failed',
                method=random.choice(self.payment_methods),
                error_code=error_code,
                timestamp=timestamp
            )
        
        print(f"  ✓ Created {num_success} successful + {num_failed} failed (75% system-side)")
    
    def generate_all_scenarios(self):
        """Generate all test scenarios"""
        print("\n" + "="*70)
        print("PAYMENT DEGRADATION GENERATOR - USING REAL RAZORPAY ERROR CODES")
        print("="*70 + "\n")
        
        base_date = datetime(2024, 1, 15)
        
        # Scenario 1: Baseline (Normal day)
        self.generate_baseline_day(base_date, num_transactions=150)
        
        # Scenario 2: Customer-side degradation (Days 2-3)
        self.generate_customer_degradation(base_date + timedelta(days=1), num_transactions=150)
        self.generate_customer_degradation(base_date + timedelta(days=2), num_transactions=150)
        
        # Scenario 3: System-side degradation (Days 4-5)
        self.generate_system_degradation(base_date + timedelta(days=3), num_transactions=150)
        self.generate_system_degradation(base_date + timedelta(days=4), num_transactions=150)
        
        print(f"\n✓ Total transactions generated: {len(self.transactions)}")
    
    def save_to_csv(self, filename='payment_transactions_v2.csv'):
        """Save all transactions to CSV"""
        df = pd.DataFrame(self.transactions)
        df.to_csv(filename, index=False)
        print(f"✓ Saved to {filename}")
        return df
    
    def generate_hourly_summary(self, filename='hourly_summary_v2.csv'):
        """Generate hourly aggregation"""
        df = pd.DataFrame(self.transactions)
        
        hourly = df.groupby(['date', 'hour']).agg({
            'transaction_id': 'count',
            'status': lambda x: (x == 'success').sum()
        }).reset_index()
        
        hourly.columns = ['date', 'hour', 'total_attempts', 'successful']
        hourly['failed'] = hourly['total_attempts'] - hourly['successful']
        hourly['success_rate'] = (hourly['successful'] / hourly['total_attempts']).round(3)
        hourly['merchant_id'] = self.merchant_id
        
        hourly = hourly[['date', 'hour', 'total_attempts', 'successful', 'failed', 'success_rate', 'merchant_id']]
        hourly.to_csv(filename, index=False)
        print(f"✓ Saved hourly summary to {filename}")
        return hourly
    
    def generate_error_distribution(self, filename='error_distribution_v2.csv'):
        """Generate error distribution by root cause"""
        df = pd.DataFrame(self.transactions)
        failed_df = df[df['status'] == 'failed']
        
        # Distribution by root cause and error code
        dist = failed_df.groupby(['date', 'root_cause', 'error_code']).size().reset_index(name='count')
        dist = dist.sort_values(['date', 'root_cause'], ascending=[True, True])
        dist.to_csv(filename, index=False)
        print(f"✓ Saved error distribution to {filename}")
        return dist
    
    def print_summary_stats(self):
        """Print summary statistics"""
        df = pd.DataFrame(self.transactions)
        
        print("\n" + "="*70)
        print("SUMMARY STATISTICS")
        print("="*70)
        
        total = len(df)
        successful = (df['status'] == 'success').sum()
        failed = (df['status'] == 'failed').sum()
        overall_success_rate = successful / total
        
        print(f"\nTotal Transactions: {total}")
        print(f"Successful: {successful} ({overall_success_rate:.1%})")
        print(f"Failed: {failed} ({1-overall_success_rate:.1%})")
        
        print(f"\nBy Root Cause:")
        root_cause_dist = df[df['status'] == 'failed']['root_cause'].value_counts()
        for cause, count in root_cause_dist.items():
            pct = count / failed * 100
            print(f"  - {cause}: {count} ({pct:.1f}%)")
        
        print(f"\nTop 10 Error Codes:")
        error_dist = df[df['status'] == 'failed']['error_code'].value_counts().head(10)
        for error, count in error_dist.items():
            cause = get_error_category(error)
            pct = count / failed * 100
            print(f"  - {error} ({cause}): {count} ({pct:.1f}%)")
        
        print(f"\nBy Payment Method:")
        method_dist = df['payment_method'].value_counts()
        for method, count in method_dist.items():
            pct = count / total * 100
            print(f"  - {method}: {count} ({pct:.1f}%)")
        
        print(f"\nDaily Success Rate:")
        daily_rates = df.groupby('date').apply(
            lambda x: (x['status'] == 'success').sum() / len(x)
        )
        for date, rate in daily_rates.items():
            print(f"  - {date}: {rate:.1%}")
        
        print(f"\nRecovery Strategies Needed:")
        recovery_dist = df[df['status'] == 'failed']['recovery_strategy'].value_counts()
        for strategy, count in recovery_dist.items():
            pct = count / failed * 100
            print(f"  - {strategy}: {count} ({pct:.1f}%)")
        
        print("\n" + "="*70 + "\n")


def main():
    """Main execution"""
    import os
    os.makedirs('data', exist_ok=True)
    os.makedirs('outputs', exist_ok=True)

    # Create generator
    generator = PaymentDegradationGeneratorV2()
    
    # Generate all scenarios
    generator.generate_all_scenarios()
    
    # Save outputs
    print("\nSaving data files...")
    df = generator.save_to_csv('data/payment_transactions_v2.csv')
    hourly_df = generator.generate_hourly_summary('outputs/hourly_summary_v2.csv')
    error_dist = generator.generate_error_distribution('outputs/error_distribution_v2.csv')
    
    # Print summary
    generator.print_summary_stats()
    
    print("✓ All data files created successfully!")
    print("\nGenerated files (with real Razorpay error codes):")
    print("  1. payment_transactions_v2.csv - Individual transaction records")
    print("  2. hourly_summary_v2.csv - Aggregated hourly metrics")
    print("  3. error_distribution_v2.csv - Error distribution by root cause")


if __name__ == '__main__':
    main()
