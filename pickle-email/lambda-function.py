import json
import boto3
from datetime import datetime

# Configuration
REGION = "us-east-2"
FROM_EMAIL = "digest@pickle.anjie.cafe"

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=REGION)
ses = boto3.client('ses', region_name=REGION)

DIGESTS_TABLE = 'pickle-user-digests'

def lambda_handler(event, context):
    print(f"Starting email delivery at {datetime.utcnow()}")
    
    try:
        # Get all ready-to-send digests
        ready_digests = get_ready_digests()
        print(f"Found {len(ready_digests)} digests ready to send")
        
        if not ready_digests:
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'No digests ready to send'})
            }
        
        sent_count = 0
        failed_count = 0
        
        for digest in ready_digests:
            email = digest['email']
            subject = digest['subject_line']
            html_content = digest['html_content']
            
            try:
                # Send email via SES
                send_email(email, subject, html_content)
                
                # Mark as sent in DynamoDB
                mark_digest_as_sent(digest)
                
                sent_count += 1
                print(f"✅ Sent digest to {email}")
                
            except Exception as e:
                print(f"❌ Failed to send to {email}: {str(e)}")
                mark_digest_as_failed(digest)
                failed_count += 1
                continue
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Email delivery complete',
                'sent': sent_count,
                'failed': failed_count,
                'total': len(ready_digests)
            })
        }
        
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def get_ready_digests():
    """Get all digests with status 'ready_to_send'"""
    try:
        table = dynamodb.Table(DIGESTS_TABLE)
        
        response = table.scan(
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':status': 'ready_to_send'}
        )
        
        return response.get('Items', [])
        
    except Exception as e:
        print(f"Error fetching ready digests: {str(e)}")
        return []

def send_email(to_email, subject, html_content):
    """Send email via Amazon SES"""
    
    try:
        response = ses.send_email(
            Source=FROM_EMAIL,
            Destination={
                'ToAddresses': [to_email]
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Html': {
                        'Data': html_content,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )
        
        message_id = response['MessageId']
        print(f"Email sent successfully to {to_email}, MessageId: {message_id}")
        return message_id
        
    except Exception as e:
        print(f"SES error sending to {to_email}: {str(e)}")
        raise e

def mark_digest_as_sent(digest):
    """Mark digest as sent in DynamoDB"""
    try:
        table = dynamodb.Table(DIGESTS_TABLE)
        
        table.update_item(
            Key={
                'email': digest['email'],
            },
            UpdateExpression='SET #status = :status, sent_at = :sent_at',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'sent',
                ':sent_at': datetime.utcnow().isoformat()
            }
        )
        
    except Exception as e:
        print(f"Error marking digest as sent: {str(e)}")
        raise e

def mark_digest_as_failed(digest):
    """Mark digest as failed in DynamoDB"""
    try:
        table = dynamodb.Table(DIGESTS_TABLE)
        
        table.update_item(
            Key={
                'email': digest['email'],
                'digest_date': digest['digest_date']
            },
            UpdateExpression='SET #status = :status, failed_at = :failed_at',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': 'failed',
                ':failed_at': datetime.utcnow().isoformat()
            }
        )
        
    except Exception as e:
        print(f"Error marking digest as failed: {str(e)}")
        pass  # Don't fail the whole process