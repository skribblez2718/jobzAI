# jobzAI

An automated job search and analysis system that helps you find and evaluate job opportunities using AI. The system analyzes job postings based on your skills, preferences, and overall fit, then delivers personalized job recommendations via email.

## Features

- **Automated Job Collection**: Fetches job postings from LinkedIn via RSS feeds. Can be extended via customization
- **AI-Powered Analysis**: Evaluates jobs based on:
  - Skill match
  - Preference alignment
  - Overall fit
- **Deduplication**: Prevents duplicate job notifications
- **Email Notifications**: Delivers personalized job recommendations

## Prerequisites

1. **RSS Feed Setup**:
   - Create an account at [rss.app](https://rss.app/)
   - Set up LinkedIn job search RSS feeds (see setup instructions below)

2. **Database**:
   - PostgreSQL (or any database supported by n8n)
   - Used for storing jobs and preventing duplicates

3. **Email Service**:
   - Gmail account with App Password enabled
   - (Alternative email services can be configured)

4. **AI Models**:
   - OpenAI API key or Open WebUI API key
   - xAI API key (or modify to use preferred models)
   - **NOTE**: You can adjust this requirement based on your model preferences

## Setup Instructions

### 1. RSS Feed Configuration

1. Perform a job search on LinkedIn
2. Copy the search results URL
3. Go to [rss.app](https://rss.app/)
4. Click "New Feed" → "LinkedIn RSS Feed"
5. Paste your LinkedIn search URL and generate the RSS feed
6. Save the RSS feed URL in the n8n RSS node configuration

### 2. Database Setup

1. Create a new PostgreSQL database
2. Note the following details:
   - Host
   - Port
   - Database name
   - Username
   - Password
3. Save the database connection details in the n8n Credentials configuration
    - **NOTE**: Postgres is not strictly required. Any supported database can be used.

### 3. Gmail App Password

1. Go to your Google Account settings
2. Search for "App passwords" in the search bar
3. Select "App passwords"
4. Generate a new app password
5. Save the generated password securely
    - **NOTE**: You can use any email service/APIs supported by n8n

### 4. Configuration

1. **n8n Setup**:
   - Import the `Generic Job Searcher.json` workflow into n8n
   - Configure the following nodes:

2. **Database Node**:
   - Update connection details with your database credentials

3. **Email Node**:
   - Set up SMTP with your credentials

4. **AI Model Nodes**:
   - Setup the credentials for the AI models
   - Adjust model parameters as needed

## Prompt Customization

The system uses several prompts for analysis. Customize these in the `prompts/` directory:

### 1. Preference Analysis
- File: prompts/system/analyze_preference_fit.md
- Replace placeholders with your job preferences

### 2. Skill Analysis
- File: prompts/user/analyze_skills.md
- Add your resume in markdown format

### 3. Overall Fit Analysis
- File: prompts/system/analyze_overall_fit.md

### 4. Other Prompts
- Review and customize other prompts as desired:
    - system prompts are locate din prompts/system/
    - user prompts are located in prompts/user/

## Usage

1. **Initial Setup**:
   - Configure all nodes in the n8n workflow
   - Test the workflow manually first node by node, pinning data as you go

2. **Scheduling**:
   - Optionally add a Schedule trigger node to run the workflow on a schedule

3. **Reviewing Results**:
   - Check your email for job recommendations
   - Each recommendation includes:
     - Job title and company
     - Match scores (skills, preferences, overall)
     - Key reasons for the match
     - Direct link to apply

## Customization
- **Overall Score Cutoff**: The overall score cutoff is set to 3. That is, only jobs rated 3 or above will be emailed. You may adjust this in the If Overall Score >= 3 node
- **Go Wild**: This flow is designed to be as simple as possible - a template basically. You can add and modify as many nodes as you want to analyze jobs in any way you want. 