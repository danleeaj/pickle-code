import json
import boto3
import requests
import os
from datetime import datetime, timedelta
import random
import urllib.parse
import re

# Configuration
REGION = "us-east-2"
NEWS_API_KEY = os.environ['NEWS_API_KEY']
MODEL_ID = "meta.llama3-3-70b-instruct-v1:0"
MAX_TOKENS = 1024
TEMPERATURE = 0.3

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=REGION)
bedrock = boto3.session.Session().client(
    service_name="bedrock-runtime",
    region_name=REGION,
)

SUBSCRIPTIONS_TABLE = 'pickle-user-subscriptions'
DIGESTS_TABLE = 'pickle-user-digests'

def lambda_handler(event, context):
    print(f"Starting daily digest generation at {datetime.utcnow()}")
    
    try:
        # Get all active subscriptions
        active_users = get_active_subscriptions()
        print(f"Found {len(active_users)} active subscriptions")
        
        if not active_users:
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'No active subscriptions found'})
            }
        
        processed_users = 0
        
        for user in active_users:
            email = user['email']
            topic = user['topic']
            
            print(f"Generating digest for {email}: {topic}")
            
            try:
                # Step 1: Generate keywords using LLM
                keywords = generate_keywords_with_llm(topic)
                print(f"Generated keywords: {keywords}")
                
                # Step 2: Fetch articles using keywords
                articles = fetch_news_articles(keywords)
                print(f"Found {len(articles)} articles")
                
                # Step 3: Generate final digest content
                digest_content = generate_digest_content(topic, articles)
                
                # Step 4: Store ready-to-send digest
                store_digest(email, topic, digest_content, len(articles))
                
                processed_users += 1
                print(f"✅ Successfully processed {email}")
                
            except Exception as e:
                print(f"Error processing user {email}: {str(e)}")
                # Store error digest so user still gets something
                error_digest = generate_error_digest(topic)
                store_digest(email, topic, error_digest, 0)
                continue
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Generated digests for {processed_users} users',
                'total_users': len(active_users)
            })
        }
        
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def get_active_subscriptions():
    """Fetch all active subscriptions from DynamoDB"""
    try:
        table = dynamodb.Table(SUBSCRIPTIONS_TABLE)
        
        response = table.scan(
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':status': 'active'}
        )
        
        return response.get('Items', [])
        
    except Exception as e:
        print(f"Error fetching subscriptions: {str(e)}")
        return []

def generate_keywords_with_llm(user_topic):
    """Generate search keywords from user topic using Bedrock"""
    
    prompt = f"""<|begin_of_text|><|start_header_id|>user<|end_header_id|>

You are a news search expert. Convert this user's topic into 5-7 keywords optimized for finding relevant news articles.

RULES:
- Extract the core subject matter and related terms
- Use words that commonly appear in news headlines
- Include both broad and specific terms
- Prefer simple, clear keywords over complex phrases
- Output ONLY the keywords, separated by commas

EXAMPLES:

Topic: "Keep me informed about electric vehicle developments"
Keywords: electric vehicles, Tesla, battery technology, EV, automotive industry, charging infrastructure

Now generate keywords for: "{user_topic}"

Keywords:<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""

    try:
        request_body = {
            "prompt": prompt,
            "max_gen_len": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "top_p": 0.9
        }
        
        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(request_body),
            contentType="application/json"
        )
        
        response_body = json.loads(response['body'].read())
        keywords_text = response_body['generation'].strip()
        
        # Clean and parse keywords
        keywords = [kw.strip() for kw in keywords_text.split(',')]
        keywords = [kw for kw in keywords if kw and len(kw) >= 2]
        
        return keywords[:7]  # Limit to 7 keywords
        
    except Exception as e:
        print(f"LLM keyword generation failed: {str(e)}")
        # Fallback: extract words from topic
        words = user_topic.lower().split()
        return [word for word in words if len(word) >= 4][:5]

def fetch_news_articles(keywords):
    """Fetch articles using first 5 keywords, then rank by relevance"""
    
    all_articles = []
    seen_urls = set()
    
    try:
        # Use first 5 keywords only
        search_keywords = keywords[:5]
        print(f"Searching with keywords: {search_keywords}")
        
        # Fetch articles for each keyword individually
        for keyword in search_keywords:
            try:
                articles = call_news_api_everything(keyword)
                print(f"Keyword '{keyword}' returned {len(articles)} articles")
                
                # Add unique articles
                for article in articles:
                    url = article.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_articles.append(article)
                        
            except Exception as e:
                print(f"Error fetching for keyword '{keyword}': {str(e)}")
                continue
        
        print(f"Total unique articles collected: {len(all_articles)}")
        
        # Rank articles by relevance to all keywords
        ranked_articles = rank_articles_by_relevance(all_articles, keywords)
        
        # Return top 10 articles
        top_articles = ranked_articles[:10]
        print(f"Selected top {len(top_articles)} articles after relevance ranking")
        
        return top_articles
        
    except Exception as e:
        print(f"Error fetching articles: {str(e)}")
        return []

def call_news_api_everything(keyword):
    """Make API call to News API /everything endpoint for a single keyword"""
    
    url = "https://newsapi.org/v2/everything"
    
    # Calculate date range (last 7 days)
    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    # URL encode the keyword
    encoded_keyword = urllib.parse.quote(keyword)
    
    params = {
        'apiKey': NEWS_API_KEY,
        'q': encoded_keyword,
        'language': 'en',
        'sortBy': 'publishedAt',  # Get most recent first
        'from': week_ago,
        'to': today,
        'pageSize': 30  # Get more articles per keyword
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])
            return articles
        else:
            print(f"News API error for '{keyword}': {response.status_code}")
            return []
            
    except Exception as e:
        print(f"Request error for keyword '{keyword}': {str(e)}")
        return []

def rank_articles_by_relevance(articles, keywords):
    """Rank articles by how many times keywords appear in all fields"""
    
    def calculate_relevance_score(article, keywords):
        """Calculate relevance score for an article"""
        score = 0
        
        # Get all text fields from the article
        title = article.get('title', '').lower()
        description = article.get('description', '').lower()
        content = article.get('content', '').lower()
        
        # Combine all text for searching
        full_text = f"{title} {description} {content}"
        
        # Count keyword occurrences
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # Count occurrences in full text
            keyword_count = len(re.findall(r'\b' + re.escape(keyword_lower) + r'\b', full_text))
            
            # Weight different fields differently
            title_count = len(re.findall(r'\b' + re.escape(keyword_lower) + r'\b', title))
            description_count = len(re.findall(r'\b' + re.escape(keyword_lower) + r'\b', description))
            content_count = len(re.findall(r'\b' + re.escape(keyword_lower) + r'\b', content))
            
            # Title matches are worth more
            score += title_count * 3
            score += description_count * 2  
            score += content_count * 1
        
        return score
    
    # Calculate relevance scores for all articles
    articles_with_scores = []
    
    for article in articles:
        score = calculate_relevance_score(article, keywords)
        articles_with_scores.append({
            'article': article,
            'relevance_score': score
        })
    
    # Sort by relevance score (highest first), then by publication date
    articles_with_scores.sort(
        key=lambda x: (x['relevance_score'], x['article'].get('publishedAt', '')), 
        reverse=True
    )
    
    # Log top articles for debugging
    print("Top 5 articles by relevance:")
    for i, item in enumerate(articles_with_scores[:5]):
        title = item['article'].get('title', 'No title')[:50]
        score = item['relevance_score']
        print(f"  {i+1}. Score: {score} - {title}...")
    
    # Return just the articles (without scores)
    return [item['article'] for item in articles_with_scores]

def generate_digest_content(topic, articles):
    """Generate final HTML email content using Bedrock"""
    
    if not articles:
        return generate_no_news_digest(topic)
    
    # Prepare articles for LLM
    articles_text = ""
    for i, article in enumerate(articles, 1):
        title = article.get('title', 'No title')
        description = article.get('description', 'No description')
        content = article.get('content', '')[:200]  # First 200 chars of content
        source = article.get('source', {}).get('name', 'Unknown')
        published = article.get('publishedAt', 'Unknown date')
        
        articles_text += f"""
Article {i}:
Title: {title}
Description: {description}
Content Preview: {content}
Source: {source}
Published: {published}
---
"""
    
    prompt = f"""<|begin_of_text|><|start_header_id|>user<|end_header_id|>

Create a personalized daily news digest email for someone interested in: "{topic}"

Requirements:
- Write a catchy subject line with pickle emoji 🥒
- Follow this exact structure:
  * Welcome message: "Welcome to your Daily Pickle on [topic of interest]!"
  * Section: "Daily Recap:"
  * Group related stories under appropriate subheadings
  * Use bullet points for key developments under each subheading
  * End with: "Thanks for reading the Pickle, see you tomorrow!"
- Use friendly, informative tone
- Format as clean HTML with proper styling
- Keep bullet points concise but informative
- Group similar stories under relevant subheadings

Articles to summarize:
{articles_text}

Format your response as:
SUBJECT: [subject line here]
HTML: [HTML email content here]

Example structure:
<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #2E8B57;">Welcome to your Daily Pickle on [topic]!</h2>

<h3>Daily Recap:</h3>

<h4>[Appropriate Subheading]</h4>
<ul>
<li>[Key development 1]</li>
<li>[Key development 2]</li>
</ul>

<h4>[Another Subheading if needed]</h4>
<ul>
<li>[Key development 3]</li>
<li>[Key development 4]</li>
</ul>

<p><strong>Thanks for reading the Pickle, see you tomorrow!</strong></p>
</body></html><|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""

    try:
        request_body = {
            "prompt": prompt,
            "max_gen_len": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "top_p": 0.9
        }
        
        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(request_body),
            contentType="application/json"
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['generation'].strip()
        
    except Exception as e:
        print(f"Error generating digest: {str(e)}")
        return generate_fallback_digest(topic, articles)

def generate_no_news_digest(topic):
    """Generate pickle-themed message when no articles found"""
    
    pickle_puns = [
        "Looks like we're in a pickle! 🥒 No major news updates today.",
        "Nothing to dill with today! 🥒 Your topic was quiet in the news.",
        "We're in a jam... or should we say pickle? 🥒 No new developments!",
        "Sweet and sour news: no updates today, but we'll keep you pickled! 🥒"
    ]
    
    pun = random.choice(pickle_puns)
    
    return f"""SUBJECT: Your Daily Pickle 🥒 - Quiet Day for {topic}
HTML: <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #2E8B57;">Your Daily Pickle 🥒</h2>
<p>{pun}</p>
<p>We searched but didn't find significant news about <strong>{topic}</strong> today.</p>
<p>We'll be back tomorrow with fresh updates. Stay pickled! 🥒</p>
</body></html>"""

def generate_error_digest(topic):
    """Generate error message when processing fails"""
    return f"""SUBJECT: Your Daily Pickle 🥒 - Technical Hiccup
HTML: <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #2E8B57;">Your Daily Pickle 🥒</h2>
<p>We ran into a technical pickle while gathering news about <strong>{topic}</strong>!</p>
<p>Our team is working on it. We'll be back tomorrow with your regular digest.</p>
<p>Stay pickled! 🥒</p>
</body></html>"""

def generate_fallback_digest(topic, articles):
    """Generate simple digest when LLM fails"""
    
    articles_list = ""
    for article in articles[:5]:
        title = article.get('title', 'No title')
        source = article.get('source', {}).get('name', 'Unknown')
        url = article.get('url', '#')
        articles_list += f'<li><a href="{url}" target="_blank"><strong>{title}</strong></a> ({source})</li>'
    
    return f"""SUBJECT: Your Daily Pickle 🥒 - {topic} Updates
HTML: <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #2E8B57;">Your Daily Pickle 🥒</h2>
<p>Here are today's updates about <strong>{topic}</strong>:</p>
<ul>{articles_list}</ul>
<p>Stay pickled! 🥒</p>
</body></html>"""

def store_digest(email, topic, digest_content, article_count):
    """Store ready-to-send digest in DynamoDB"""
    
    try:
        table = dynamodb.Table(DIGESTS_TABLE)
        
        today = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Parse subject and HTML from digest content
        subject_line = "Your Daily Pickle 🥒"
        html_content = digest_content
        
        if "SUBJECT:" in digest_content and "HTML:" in digest_content:
            parts = digest_content.split("HTML:")
            subject_part = parts[0].replace("SUBJECT:", "").strip()
            html_content = parts[1].strip()
            subject_line = subject_part
        
        item = {
            'email': email,
            'digest_date': today,
            'topic': topic,
            'subject_line': subject_line,
            'html_content': html_content,
            'article_count': article_count,
            'generated_at': datetime.utcnow().isoformat(),
            'status': 'ready_to_send',
            'ttl': int((datetime.utcnow() + timedelta(days=3)).timestamp())
        }

        print(html_content)
        
        table.put_item(Item=item)
        print(f"Stored digest for {email}")
        
    except Exception as e:
        print(f"Error storing digest: {str(e)}")
        raise e