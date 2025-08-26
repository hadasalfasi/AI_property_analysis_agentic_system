# Property Analysis System

A system designed to extract, analyze, and generate comprehensive property reports for real estate planning in Los Angeles using data from ZIMAS and Tavily, combined with AI-enhanced insights.

## 🏗️ Project Overview

This system scrapes property data from Los Angeles City Planning (ZIMAS) and supplements it with web search results from Tavily. The extracted data is then processed by an AI model to generate a detailed and actionable property analysis report, focusing on zoning, permits, overlays, and other property-related data.

### Key Features

- **ZIMAS Data Extraction**: Scrapes zoning, permits, and other planning data for properties in Los Angeles.
- **Tavily Integration**: Enhances the analysis with supplementary property-related web search results.
- **AI Processing**: Uses a large language model (LLM) for generating actionable insights from the data.
- **Real-time Reporting**: Generates detailed reports based on the extracted and analyzed data.
- **Interactive Frontend**: Allows users to query property data through a conversational interface in Streamlit.

## 🛠️ Technical Stack

- **Backend**: FastAPI
- **Frontend**: Streamlit
- **AI Framework**: LangGraph (using a large language model for analysis)
- **Web Scraping**: Playwright (for scraping ZIMAS and Tavily data)
- **Containerization**: Docker
- **API Integrations**: Tavily (for real-time pricing), OpenRouter (for AI processing)
- **Database**: Pinecone (for vector-based data storage)

## 📋 Prerequisites

Before running the application, ensure you have:

- Docker and Docker Compose installed
- API keys for:
  - OpenRouter AI
  - Tavily Search API
  - LangSmith (for monitoring)

## 🚀 Quick Start with Docker

### 1. Clone and Setup

```bash
# Clone the project
git clone https://github.com/hadasalfasi/AI_property_analysis_agentic_system.git
cd property-analysis-system

# Build and start the containers
docker-compose up --build
