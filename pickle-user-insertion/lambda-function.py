import json
import boto3
import time
from datetime import datetime

REGION = "us-east-2"
dynamodb = boto3.resource('dynamodb', region_name=REGION)

SUBSCRIPTIONS_TABLE = 'pickle-user-subscriptions'

def lambda_handler(event, context):

    print(f"Received event: {json.dumps(event)}")
    
    try:

        if 'body' in event:
            body = json.loads(event['body'])
        else:
            body = event
            
        email = body.get('email')
        topic = body.get('topic')
        
        if not email or not topic:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Email and topic are required'})
            }
        
        print(f"Processing request for {email}: {topic}")
        
        # Store subscription in DynamoDB
        create_subscription(email, topic)
        
        # Return success
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'POST, OPTIONS'
            },
            'body': json.dumps({
                'message': 'Subscription created successfully!',
                'email': email,
                'topic': topic,
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

def create_subscription(email, topic):
    """Create subscription with email and topic, and store in database."""
    try:
        table = dynamodb.Table(SUBSCRIPTIONS_TABLE)
        
        # Calculate TTL (2 days from now)
        ttl = int(time.time()) + (2 * 24 * 60 * 60)
        
        item = {
            'email': email,
            'topic': topic,
            'created_at': datetime.utcnow().isoformat(),
            'expires_at': datetime.fromtimestamp(ttl).isoformat(),
            'ttl': ttl,
            'status': 'active',
            'last_processed': datetime.utcnow().isoformat()
        }
        
        table.put_item(Item=item)
        print(f"Successfully created subscription for {email}")
        
    except Exception as e:
        print(f"DynamoDB error: {str(e)}")
        raise e