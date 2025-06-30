# The Daily Pickle
Submission for AWS Lambda Hackathon 2025

The Daily Pickle is a news curation service that delivers personalized daily digests to users' inboxes based on their topics of interest. It is built entirely on AWS serverless infrastructure.

## AWS Services Used

* **Lambda**: Serverless functions for all logic
* **API Gateway**: REST API endpoints for subscribing
* **DynamoDB**: NoSQL database for backend
* **SES**: Email delivery
* **EventBridge**: Function scheduling, daily newsletters
* **Bedrock**: LLM provider

AWS Lambda is the backbone of the Daily Pickle, handling all server-side logic through three functions:

1. Registration (pickle-user-insertion)
Upon API call, this function inserts the user's email and topic of interest into a DynamoDB database for further processing.
2. Everything in-between (pickle-user-prompt)
Forgive the arbitrary name. This function was named before I decided to put everything together to get a MVP out. This function is triggered everyday at 8AM by EventBridge. It takes the user's topic of interest and calls Llama 3.1 80B using Bedrock to extract news search-friendly keywords. News API is then used to search the keywords up. Each returned article is assigned a weighted score based on how many times keywords appear in their content, and the top 10 articles are sent back to the LLM for summary and digest writing. These digests are then stored, along with the respective user emails, into another database.
3. Email sending (pickle-email)
At 9AM, EventBridge triggers this function to send all unsent emails.

## Deployment

A simple HTML file was written and hosted in Github [here](https://danleeaj.github.io/pickle/), with some simple JavaScript to make API calls.

## Contact

Feel free to contact me at [anjie.wav@gmail.com], to talk about anything!

Github: [danleeaj](https://github.com/danleeaj)
LinkedIn: [An Jie Lee](https://www.linkedin.com/in/anjie-lee)
