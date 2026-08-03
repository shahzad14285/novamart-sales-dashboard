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

## ✨ Key Features

### 📊 Sales Performance Analytics

* Interactive analysis of overall sales performance
* KPI-driven business performance monitoring
* Visual exploration of sales trends and patterns

### 📈 Interactive Dashboards

* Interactive visual dashboards for exploring business and sales data
* Dynamic filtering and data exploration
* Clear visual presentation of key business metrics and insights

### 🛍️ Product & Category Analysis

* Analysis of product-level performance
* Category-level performance analysis
* Identification of high- and low-performing areas

### 🌍 Business Performance Analysis

* Analysis across relevant business dimensions
* Comparative performance evaluation
* Identification of trends, patterns, and areas requiring attention

### 🎯 Decision Support

* Converts analytical findings into actionable business insights
* Supports data-driven decision-making
* Helps stakeholders identify opportunities and performance gaps

### 🤖 AI-Assisted Development

* AI-assisted solution planning and development
* Structured prompt engineering and implementation workflows
* AI-assisted troubleshooting and iterative refinement
* Human-led testing, validation, review, and quality improvement

### 🧪 Testing & Quality Assurance

* Functional testing of implemented features
* Iterative testing and refinement throughout development
* Validation of outputs and user-facing functionality
* Continuous improvement based on testing results and review

### 📚 Documentation & Version Control

* Structured project documentation
* Architecture and solution documentation
* Git-based version control
* GitHub-based project management and release workflow


---

## 🏗️ Solution Architecture

The NovaMart Sales Intelligence Dashboard follows a structured, layered architecture designed to separate data ingestion, processing, analytics, and business insight generation.

```text
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

### Architecture Flow

**1. Data Sources**
CSV and Excel files serve as the primary data inputs for the dashboard.

**2. Upload Center**
Provides the entry point for users to upload and introduce business data into the solution.

**3. DataLoader**
Handles the loading and preparation of uploaded data for downstream processing and analysis.

**4. Filtering Engine**
Supports data filtering and focused analysis based on relevant business dimensions.

**5. Analytics Layer**
Processes the available data to generate analytical outputs and performance metrics.

**6. KPI Layer**
Transforms analytical results into key performance indicators that help monitor business performance.

**7. Executive Analytics**
Presents higher-level analytical views designed to support management-level understanding of business performance.

**8. Business Insights**
Translates analytical outputs into meaningful business insights to support informed decision-making.

This architecture reflects the project's focus on creating a structured path from **raw business data → analytics → KPIs → executive understanding → actionable business insights**.

---

## 📁 Project Structure

```text
NovaMart_Sales_Dashboard/
│
├── assets/                 # Static assets and supporting visual resources
│
├── components/             # Reusable application components
│   ├── analytics/          # Analytics-related components and functionality
│   ├── footer.py           # Application footer
│   ├── header.py           # Application header
│   ├── kpi_cards.py        # KPI card components
│   ├── sidebar.py          # Sidebar and navigation components
│   └── upload_center.py    # Data upload interface and functionality
│
├── config/                 # Application configuration
│
├── data/                   # Data files and data-related resources
│
├── docs/                   # Project and solution documentation
│
├── pages/                  # Dashboard pages and application views
│
├── tests/                  # Testing and quality assurance resources
│
├── utils/                  # Shared utility functions and supporting modules
│
├── app.py                  # Main application entry point
├── requirements.txt        # Python dependencies
└── README.md               # Project documentation
```

The project structure follows a modular organization that separates reusable components, analytics functionality, configuration, data resources, documentation, dashboard pages, testing, and utility modules.

This structure supports maintainability, iterative development, testing, and future expansion of the solution.

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

## 🛠️ Technology Stack

### Application & Dashboard

* **Python** — Application and data processing layer
* **Streamlit** — Interactive web application and dashboard framework
* **Plotly** — Interactive data visualization

### Data & Analytics

* **Pandas** — Data manipulation and analytical processing
* **CSV / Excel** — Primary data input formats

### Development & Version Control

* **Git** — Version control
* **GitHub** — Repository management, collaboration, and release tracking

### AI-Assisted Development

* **ChatGPT** — Used for solution planning, prompt engineering, problem analysis, implementation guidance, and generating structured development instructions
* **Claude** — Used to assist with implementation, development, troubleshooting, and iterative refinement

### Creative & Supporting AI Tools

* **Canva** — Visual design and presentation workflows
* **ElevenLabs** — AI-assisted voice and audio workflows

### Development Approach

The project follows an **AI-assisted development workflow** in which AI tools support planning and implementation while the solution is subsequently tested, reviewed, validated, and refined through an iterative process.

The overall workflow is:

**Business Requirements → Solution Design → Prompt Engineering → AI-Assisted Implementation → Testing → Review → Refinement → Documentation → Release**

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
