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

## 🚀 Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/shahzad14285/novamart-sales-dashboard.git
```

### 2. Move into the Project Directory

```bash
cd novamart-sales-dashboard
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the Application

```bash
streamlit run app.py
```

Once the application starts, open the local Streamlit URL displayed in your terminal to access the NovaMart Sales Intelligence Dashboard.

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

## 🧪 Testing & Quality Assurance

NovaMart follows a combination of **automated and manual testing** to validate core functionality, analytical outputs, and user-facing behavior.

### Automated Testing

Automated tests cover key solution components, including:

* **Data Loader Tests** — Validate data loading and preparation functionality.
* **Filter Engine Tests** — Validate filtering logic and data selection behavior.
* **Analytics Tests** — Validate analytical processing and calculated outputs.
* **Business Insights Tests** — Validate business insight generation and related analytical functionality.

### Manual Testing

Manual testing is used to validate end-to-end functionality and user-facing behavior, including:

* **Upload Validation** — Verifying data upload functionality and input handling.
* **KPI Verification** — Reviewing and validating KPI calculations and displayed results.
* **Filter Testing** — Confirming that interactive filters produce the expected analytical results.
* **Regression Testing** — Rechecking existing functionality after changes and enhancements to help ensure that previously working features continue to operate as expected.

The testing process is part of an iterative development workflow:

**Implement → Test → Review → Identify Issues → Refine → Retest**

This approach supports continuous improvement and helps maintain the reliability and consistency of the solution as development progresses.

---
## 📈 Current Development Progress

| Development Area         | Status         |
| ------------------------ | -------------- |
| Project Planning         | ✅ Completed    |
| Solution Architecture    | ✅ Completed    |
| Foundation               | ✅ Completed    |
| Upload Center            | ✅ Completed    |
| Dynamic KPIs             | ✅ Completed    |
| Interactive Filters      | ✅ Completed    |
| Executive Analytics      | ✅ Completed    |
| Business Insights        | ✅ Completed    |
| Export Center            | 🔄 In Progress |
| Performance Optimization | 🔄 In Progress |
| Deployment               | ⏳ Planned      |

### 🏷️ Release History

* **v0.1.0** — Foundation and initial project structure
* **v0.2.0** — Core dashboard functionality and analytics
* **v0.3.0** — Interactive dashboard enhancements
* **v0.4.0** — Advanced analytics and business insight capabilities
* **v0.5.0** — Current development milestone

The project has progressed through **Sprint 6.9**, with multiple structured development sprints and Git-based releases completed through **v0.5.0**.

### 🛣️ Roadmap

#### Next Development Priorities

* Complete Export Center functionality
* Continue Performance Optimization
* Further UI and usability improvements
* Continue testing and refinement
* Prepare the solution for deployment

#### Future Direction

* Cloud Deployment
* Production-readiness improvements
* Further scalability and performance enhancements
* Additional business intelligence capabilities

### 🎯 Long-Term Vision

The long-term objective is to evolve NovaMart into a production-ready business intelligence solution that demonstrates how business requirements, analytics, interactive visualization, AI-assisted development, and structured solution architecture can come together to support data-driven decision-making.

---

## 🤖 AI-Assisted Development

NovaMart is developed using a structured AI-assisted solution development workflow that combines business requirements, solution planning, AI-assisted implementation, testing, review, refinement, documentation, and version control.

The development workflow includes:

**Business Requirements**
↓
**Solution Planning & Architecture**
↓
**ChatGPT — Prompt Engineering, Planning & Development Guidance**
↓
**Claude — AI-Assisted Implementation & Refinement**
↓
**Manual Testing & Validation**
↓
**Review & Iterative Refinement**
↓
**Documentation**
↓
**Git & GitHub — Version Control & Release Management**

### AI-Assisted Development Approach

The project uses AI tools as development assistants within a structured workflow.

* **ChatGPT** is used for problem analysis, solution planning, prompt engineering, generating structured implementation instructions, exploring approaches, and supporting troubleshooting.
* **Claude** is used to assist with implementation, building solution components, troubleshooting, and iterative refinement.
* The resulting implementation is then **manually tested, reviewed, validated, and refined** to identify issues and improve functionality.
* **Git and GitHub** are used for version control, project management, and release tracking.
* The solution is organized using a **modular architecture** to support maintainability and future expansion.

The overall approach is:

> **AI-assisted development + human-led testing, validation, review, and refinement**

This project demonstrates a practical approach to using modern AI tools to accelerate solution development while maintaining structured testing, quality review, documentation, and version control.

---

## 👨‍💻 Author

**Shahzad Ali**

AI Solution Architect | AI-Assisted Solution Development | AI & Business Solutions | Data & Business Analytics

NovaMart is a portfolio project demonstrating practical experience in business intelligence, analytics, solution design, AI-assisted development, testing, and iterative solution refinement.

---

## 📄 License

This project is intended for educational, learning, and professional portfolio demonstration purposes.
