# 📊 NovaMart Sales Dashboard

> **An AI-assisted Sales Intelligence Dashboard designed to transform business data into interactive analytics, KPIs, executive insights, and actionable decision support.**

NovaMart transforms raw sales data into interactive dashboards, executive analytics and business insights through a clean, modular and scalable architecture.

---

## 📌 Project Overview

NovaMart Sales Intelligence Dashboard is an AI-assisted business intelligence solution designed to transform sales data into interactive analytics, key performance indicators (KPIs), visual insights, and actionable decision support.

The project demonstrates an end-to-end approach to developing a practical business intelligence solution, combining business requirements, solution architecture, data analytics, interactive visualization, AI-assisted development, testing, iterative refinement, and structured documentation.

The solution is designed to help business stakeholders:

* Monitor overall sales performance and key business KPIs
* Analyze sales trends and performance over time
* Explore product and category performance
* Evaluate regional and other business dimensions
* Identify patterns and areas requiring attention
* Interact with data through dashboards and visual analytics
* Support more informed, data-driven business decisions

The project is being developed as a flagship portfolio initiative demonstrating how business understanding, analytics, AI-assisted development, and structured solution design can be combined to create a practical business intelligence solution.

The development process follows a structured lifecycle:

**Business Requirements → Solution Architecture → AI-Assisted Development → Testing & Validation → Iterative Refinement → Documentation → Release**

The project also demonstrates the use of AI-assisted development workflows, where AI tools are used to support solution planning, implementation, troubleshooting, and refinement, followed by human-led testing, review, validation, and continuous improvement.


---

## ✨ Features

### 📂 Data Management

- ✅ CSV Upload
- ✅ Excel Upload
- ✅ Automatic Data Validation
- ✅ Error Handling
- ✅ Missing Value Processing

### 📊 Analytics

- ✅ Dynamic KPI Engine
- ✅ Executive Analytics
- ✅ Revenue Analysis
- ✅ Product Analysis
- ✅ Regional Analysis
- ✅ Business Insights

### 🎛 Interactive Dashboard

- ✅ Global Filters
- ✅ Dynamic Charts
- ✅ Responsive KPI Cards
- ✅ Real-time Updates

### 🏗 Software Engineering

- ✅ Modular Architecture
- ✅ Reusable Components
- ✅ Separation of Concerns
- ✅ Automated Testing
- ✅ Git Version Control
- ✅ AI-assisted Development Workflow

---

## 🏗 Architecture

```
CSV / Excel
      │
      ▼
Upload Center
      │
      ▼
DataLoader
      │
      ▼
Filtering Engine
      │
      ▼
Analytics Layer
      │
 ┌────┴───────────┐
 ▼                ▼
KPIs      Executive Analytics
                     │
                     ▼
             Business Insights
```

---

## 📁 Project Structure

```
NovaMart_Sales_Dashboard/

├── assets/
├── components/
│   ├── analytics/
│   ├── footer.py
│   ├── header.py
│   ├── kpi_cards.py
│   ├── sidebar.py
│   └── upload_center.py
│
├── config/
├── data/
├── docs/
├── pages/
├── tests/
├── utils/
│
├── app.py
├── requirements.txt
└── README.md
```

---

## 📸 Screenshots

### 🏠 Home Page

![Home Page](assets/screenshots/home-page.png)

---

### 📊 Dashboard Overview

![Dashboard](assets/screenshots/dashboard-overview.png)

---

### 🎛 Interactive Filters

![Filters](assets/screenshots/interactive-filters.png)

---

### 📈 Executive Analytics

![Executive Analytics](assets/screenshots/executive-analytics.png)

---

### 💡 Business Insights

![Business Insights](assets/screenshots/business-insights.png)

## ⚙ Technology Stack

| Category | Technology |
|-----------|------------|
| Language | Python |
| Framework | Streamlit |
| Visualization | Plotly |
| Data Processing | Pandas |
| Excel Support | OpenPyXL |
| Testing | Pytest |
| Version Control | Git |
| Repository | GitHub |

---

## 🚀 Installation

Clone the repository

```bash
git clone https://github.com/shahzad14285/novamart-sales-dashboard.git
```

Move into the project

```bash
cd novamart-sales-dashboard
```

Install dependencies

```bash
pip install -r requirements.txt
```

Run the application

```bash
streamlit run app.py
```

---

## 📂 Supported Dataset Format

Current required columns:

| Column | Required |
|----------|---------|
| date | ✅ |
| revenue | ✅ |
| orders | ✅ |

Optional columns:

- product
- customer
- region

NovaMart automatically detects optional columns and enables related analytics dynamically.

---

## 📊 Dashboard Modules

- Home
- Dashboard
- Sales Analytics
- Customers
- Products
- Settings

---

## 🧪 Testing

NovaMart includes both automated and manual testing.

### Automated

- Data Loader Tests
- Filter Engine Tests
- Analytics Tests
- Business Insights Tests

### Manual

- Upload Validation
- KPI Verification
- Filter Testing
- Regression Testing

---

## 📈 Current Development Progress

| Sprint | Status |
|----------|--------|
| Project Planning | ✅ |
| Architecture | ✅ |
| Foundation | ✅ |
| Upload Center | ✅ |
| Dynamic KPIs | ✅ |
| Interactive Filters | ✅ |
| Executive Analytics | ✅ |
| Business Insights | ✅ |
| Export Center | 🔄 |
| Performance Optimization | 🔄 |
| Deployment | ⏳ |

---

## 🛣 Roadmap

### Version 0.3

- Export Center
- Excel Export
- CSV Export

### Version 0.4

- Performance Improvements
- UI Polish
- Better Caching

### Version 0.5

- Cloud Deployment

### Version 1.0

Production-ready Business Intelligence Dashboard

---

## 🤖 AI-Assisted Development

NovaMart is developed using a modern AI-assisted engineering workflow.

Development combines:

- ChatGPT
- Claude Code
- Git
- GitHub
- Manual Testing
- Modular Software Architecture

Every feature is planned, implemented, tested, documented and version-controlled.

---

## 👨‍💻 Author

**Shahzad**

Portfolio Project — Business Intelligence Dashboard

---

## 📄 License

This project is intended for educational and portfolio purposes
