"""
Razorpay Error Code Mapping to Root Causes
Maps real Razorpay errors to CUSTOMER_SIDE, SYSTEM_SIDE, and MERCHANT_SIDE causes
"""

RAZORPAY_ERROR_MAPPING = {
    # ============================================================================
    # CUSTOMER-SIDE ERRORS (Source: Customer made an error)
    # Recovery Strategy: Retry with alternate method or ask customer to fix
    # ============================================================================
    "CUSTOMER_SIDE": {
        "errors": {
            # Card Issues
            "card_expired": {
                "description": "The card has expired.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": True
            },
            "card_number_invalid": {
                "description": "The card number is invalid.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            "card_type_invalid": {
                "description": "The card type is invalid.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            "debit_instrument_blocked": {
                "description": "The card has been blocked by issuer or customer.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": True
            },
            
            # Funds/Balance Issues
            "insufficient_funds": {
                "description": "Customer does not have sufficient funds.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": True
            },
            "transaction_limit_exceeded": {
                "description": "Customer has exceeded credit/debit limit on card.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": True
            },
            "transaction_daily_limit_exceeded": {
                "description": "Customer has exceeded daily transaction limit.",
                "recovery": "WAIT_RETRY",
                "razorpay_source": "customer",
                "common": True
            },
            "transaction_frequency_limit_exceeded": {
                "description": "NPCI frequency limit exhausted.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": False
            },
            
            # Authentication Issues
            "incorrect_otp": {
                "description": "Customer entered incorrect OTP.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": True
            },
            "otp_expired": {
                "description": "OTP has expired.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": True
            },
            "otp_attempts_exceeded": {
                "description": "OTP attempts exceeded.",
                "recovery": "WAIT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            "authentication_failed": {
                "description": "3D secure or OTP authentication failed.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": True
            },
            "incorrect_pin": {
                "description": "Customer entered incorrect PIN.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            "pin_attempts_exceeded": {
                "description": "PIN attempts exceeded.",
                "recovery": "WAIT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            
            # Payment Cancellation/Timeout
            "payment_cancelled": {
                "description": "Customer explicitly cancelled the payment.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            "payment_timed_out": {
                "description": "Customer did not complete within specified time.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": True
            },
            
            # UPI Issues
            "invalid_vpa": {
                "description": "Customer entered incorrect VPA.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            "transaction_on_vpa_restricted": {
                "description": "Transaction on VPA blocked by PSP.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": False
            },
            
            # Netbanking
            "user_not_registered_for_netbanking": {
                "description": "Bank account not registered for netbanking.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": False
            },
            
            # Other Customer Issues
            "incorrect_atm_pin": {
                "description": "Incorrect ATM PIN entered.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            "incorrect_card_details": {
                "description": "Incorrect card details entered.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": False
            },
            "incorrect_cvv": {
                "description": "Incorrect CVV entered.",
                "recovery": "PROMPT_RETRY",
                "razorpay_source": "customer",
                "common": True
            },
            "payment_risk_check_failed": {
                "description": "Payment declined due to risk checks.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "customer",
                "common": True
            },
        },
        "recovery_strategies": {
            "RETRY_ALTERNATE_METHOD": "Retry with different payment method (UPI if was card, etc)",
            "PROMPT_RETRY": "Ask customer to retry with correct details",
            "WAIT_RETRY": "Wait 24h or ask customer to use different method",
        }
    },

    # ============================================================================
    # SYSTEM-SIDE ERRORS (Source: Gateway or Bank)
    # Recovery Strategy: Exponential backoff, retry intelligently
    # ============================================================================
    "SYSTEM_SIDE": {
        "errors": {
            # Bank Issues
            "bank_technical_error": {
                "description": "Bank/CBS facing technical problems.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": True
            },
            "bank_not_available": {
                "description": "Bank not available due to downtime.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": True
            },
            "bank_cutoff_in_progress": {
                "description": "Bank CBS cutoff in progress.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": False
            },
            
            # Gateway/Network Issues
            "gateway_technical_error": {
                "description": "Technical error at payment gateway.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": True
            },
            "payment_failed": {
                "description": "Payment failed at bank/gateway, no specific code.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": True
            },
            "issuer_technical_error": {
                "description": "Technical error at card issuer.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": True
            },
            "invalid_response_from_gateway": {
                "description": "Invalid response received from gateway.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": False
            },
            "request_timed_out": {
                "description": "Request timed out.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": True
            },
            
            # Razorpay Server Issues
            "server_error": {
                "description": "Technical error at Razorpay's server.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "razorpay",
                "common": True
            },
            
            # UPI PSP Issues
            "psp_app_not_available": {
                "description": "PSP app not available due to downtime.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "gateway",
                "common": False
            },
            "upi_app_technical_error": {
                "description": "Technical error at customer's PSP.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": False
            },
            "psp_not_available": {
                "description": "PSP not available.",
                "recovery": "RETRY_ALTERNATE_METHOD",
                "razorpay_source": "gateway",
                "common": False
            },
            "vpa_resolution_failed": {
                "description": "UPI network failed to validate VPA.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": False
            },
            
            # Traffic/Load Issues
            "payment_declined_due_to_high_traffic": {
                "description": "Payment declined due to high traffic.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": True
            },
            
            # Pending States
            "payment_pending": {
                "description": "Payment is pending and not completed.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": False
            },
            "collect_request_pending": {
                "description": "Collect request already pending.",
                "recovery": "EXPONENTIAL_BACKOFF",
                "razorpay_source": "gateway",
                "common": False
            },
        },
        "recovery_strategies": {
            "EXPONENTIAL_BACKOFF": "Retry with exponential backoff (5s, 10s, 20s, stop after 3)",
            "RETRY_ALTERNATE_METHOD": "Ask customer to retry with different payment method",
        }
    },

    # ============================================================================
    # MERCHANT-SIDE ERRORS (Source: Business/Merchant configuration)
    # Recovery Strategy: Flag for manual review, DO NOT auto-retry
    # ============================================================================
    "MERCHANT_SIDE": {
        "errors": {
            # Configuration Issues
            "payment_method_not_enabled": {
                "description": "Payment method not enabled for merchant.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": True
            },
            "bank_not_enabled": {
                "description": "Selected bank not enabled for merchant.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "card_network_not_enabled": {
                "description": "Card network (Visa/Mastercard) not enabled.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "recurring_payment_not_enabled": {
                "description": "Recurring payments not enabled.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "upi_intent_not_enabled": {
                "description": "UPI Intent flow not enabled.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "upi_collect_not_enabled": {
                "description": "UPI Collect flow not enabled.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            
            # Request/Data Issues
            "invalid_request": {
                "description": "The request is invalid.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": True
            },
            "input_validation_failed": {
                "description": "Wrong request/input in payment request.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": True
            },
            "invalid_amount": {
                "description": "The amount provided is invalid.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "invalid_currency": {
                "description": "Currency not supported or invalid.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "invalid_order_id": {
                "description": "Order ID missing or invalid.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": True
            },
            "order_amount_mismatch": {
                "description": "Amount mismatch between order and payment.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": True
            },
            "order_payment_method_mismatch": {
                "description": "Method mismatch between order and payment.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            
            # Account/Merchant Issues
            "merchant_not_activated": {
                "description": "Merchant account is not activated.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "live_mode_not_enabled": {
                "description": "Live mode not enabled (using test keys).",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            
            # Duplicate/Already Paid
            "order_already_paid": {
                "description": "Order already has successful payment.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "duplicate_request": {
                "description": "Duplicate request submitted.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            
            # Limits/Compliance
            "amount_less_than_minimum_amount": {
                "description": "Amount less than minimum fees.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "compliance_violation": {
                "description": "Payment violates compliance.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
            "refund_limit_crossed": {
                "description": "Refund limit has been crossed.",
                "recovery": "FLAG_FOR_REVIEW",
                "razorpay_source": "business",
                "common": False
            },
        },
        "recovery_strategies": {
            "FLAG_FOR_REVIEW": "STOP retries. Flag for merchant review. Escalate to support.",
        }
    }
}

def get_error_category(error_code):
    """Get the root cause category for a Razorpay error code"""
    for category, data in RAZORPAY_ERROR_MAPPING.items():
        if error_code in data["errors"]:
            return category
    return "UNKNOWN"

def get_recovery_strategy(error_code):
    """Get the recovery strategy for a Razorpay error code"""
    for category, data in RAZORPAY_ERROR_MAPPING.items():
        if error_code in data["errors"]:
            error_info = data["errors"][error_code]
            strategy = error_info["recovery"]
            return data["recovery_strategies"].get(strategy, "UNKNOWN")
    return "UNKNOWN"

def is_common_error(error_code):
    """Check if this is a common error (frequently seen in production)"""
    for category, data in RAZORPAY_ERROR_MAPPING.items():
        if error_code in data["errors"]:
            return data["errors"][error_code]["common"]
    return False

def get_retryable_errors():
    """Get all retryable error codes"""
    retryable = []
    for category, data in RAZORPAY_ERROR_MAPPING.items():
        for error_code, info in data["errors"].items():
            if info["recovery"] in ["EXPONENTIAL_BACKOFF", "RETRY_ALTERNATE_METHOD", "WAIT_RETRY"]:
                retryable.append(error_code)
    return retryable

def get_non_retryable_errors():
    """Get all non-retryable error codes (require manual review)"""
    non_retryable = []
    for category, data in RAZORPAY_ERROR_MAPPING.items():
        for error_code, info in data["errors"].items():
            if info["recovery"] == "FLAG_FOR_REVIEW":
                non_retryable.append(error_code)
    return non_retryable

def get_common_errors_by_category():
    """Get most common errors by category"""
    common = {}
    for category, data in RAZORPAY_ERROR_MAPPING.items():
        common[category] = [
            err_code for err_code, err_info in data["errors"].items()
            if err_info["common"]
        ]
    return common

if __name__ == "__main__":
    print("Razorpay Error Mapping Summary")
    print("=" * 70)
    
    for category, data in RAZORPAY_ERROR_MAPPING.items():
        print(f"\n{category}")
        print(f"  Total errors: {len(data['errors'])}")
        common_count = sum(1 for err in data['errors'].values() if err['common'])
        print(f"  Common errors: {common_count}")
        print(f"  Recovery strategies: {', '.join(data['recovery_strategies'].keys())}")
    
    print(f"\n\nTotal retryable errors: {len(get_retryable_errors())}")
    print(f"Total non-retryable errors: {len(get_non_retryable_errors())}")
    
    print("\n\nExample usage:")
    print(f"get_error_category('insufficient_funds') = {get_error_category('insufficient_funds')}")
    print(f"get_recovery_strategy('insufficient_funds') = {get_recovery_strategy('insufficient_funds')}")
    print(f"is_common_error('insufficient_funds') = {is_common_error('insufficient_funds')}")
