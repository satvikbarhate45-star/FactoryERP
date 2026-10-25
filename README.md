# PharmaERP (FactoryERP) 🏭💊

> **Enterprise Pharmaceutical ERP & Machine Learning Platform**  
> An intelligent, autonomous factory management and operations platform featuring predictive maintenance, machine learning imputation, multilingual AI assistant, dual database synchronization, and role-based supervisory dashboards.

---

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.0%2B-092E20.svg?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-4169E1.svg?logo=postgresql&logoColor=white)](https://supabase.com/)
[![Scikit-Learn](https://img.shields.io/badge/Scikit--Learn-ML%20Analytics-F7931E.svg?logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)
[![Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini-4285F4.svg?logo=google&logoColor=white)](https://ai.google.dev/)
[![APScheduler](https://img.shields.io/badge/Automation-APScheduler-green.svg)](https://apscheduler.readthedocs.io/)

---

## 📑 Table of Contents

- [Overview](#-overview)
- [System Architecture](#-system-architecture)
- [Key Features](#-key-features)
  - [1. Autonomous Decision Engine & ML Analytics](#1-autonomous-decision-engine--ml-analytics)
  - [2. Predictive Maintenance & Equipment Health](#2-predictive-maintenance--equipment-health)
  - [3. Multilingual AI Assistant (Gemini)](#3-multilingual-ai-assistant-gemini)
  - [4. Dual Database Router & Offline Resilience](#4-dual-database-router--offline-resilience)
  - [5. Role-Based Access & Supervisor Control](#5-role-based-access--supervisor-control)
- [Project Directory Structure](#-project-directory-structure)
- [Prerequisites](#-prerequisites)
- [Installation & Setup](#-installation--setup)
- [Environment Variables](#-environment-variables)
- [Database Setup & Mock Data Seeding](#-database-setup--mock-data-seeding)
- [Running the Application](#-running-the-application)
- [Default Demo Credentials](#-default-demo-credentials)
- [API & URL Routing](#-api--url-routing)
- [Contributing & License](#-contributing--license)

---

## 🌟 Overview

**PharmaERP** is built specifically for pharmaceutical and continuous chemical manufacturing plants where precision, compliance, zero-downtime, and rapid anomaly response are paramount. 

The platform bridges real-time physical plant operations with advanced predictive analytics:
- Prevents catastrophic equipment failures via vibration, temperature, and wear telemetry.
- Resolves inventory deficits and bottlenecks using historical pattern deliberation.
- Imputes missing production records through regression models when plant network drops occur.
- Empowers shop-floor workers and plant directors alike with conversational AI available in English, Hindi, and Marathi with voice playback.

---

## 🏗 System Architecture

```mermaid
graph TD
    Client["Shop Floor UI / Desktop / Mobile Browser"] --> NGINX["Web Server / WSGI"]
    NGINX --> DjangoApp["Django 5.0 Core Application"]
    
    subgraph Modular Apps
        DjangoApp --> Acc["apps.accounts (Auth, Shifts, KYC)"]
        DjangoApp --> Prod["apps.production (Logs, Targets, Payroll)"]
        DjangoApp --> Maint["apps.maintenance (Sensors, Work Orders)"]
        DjangoApp --> Inv["apps.inventory (Stock, Critical Thresholds)"]
        DjangoApp --> Logist["apps.logistics (Dispatches, Transits)"]
        DjangoApp --> AIChat["apps.ai_chat (Gemini, Context Injector, TTS)"]
    end
    
    subgraph Intelligence & Background Services
        Prod --> ML["ML Scheduler & Imputation (Scikit-Learn)"]
        Prod --> Engine["Autonomous Decision Engine"]
        Maint --> Sched["APScheduler Engine (Cron / Intervals)"]
        AIChat --> Gemini["Google Gemini 1.5/2.0/3.0 Models"]
    end
    
    subgraph Database Layer
        DjangoApp --> Router["DB Router & Fault-Tolerant Middleware"]
        Router -->|Primary| Supabase["Supabase PostgreSQL Pooler"]
        Router -->|Failover / Local| SQLite["Local SQLite Fallback"]
    end
```

---

## 🚀 Key Features

### 1. Autonomous Decision Engine & ML Analytics
- **Historical Deliberation**: The decision engine analyzes 30-day trailing rolling statistics before issuing autonomous resolutions for inventory shortages and yield dips.
- **Automated Data Imputation**: When production entries are skipped during network outages, regression models dynamically generate missing shift entries based on historical equipment performance.
- **Payroll & Performance Calculation**: Automated yield vs. target ratio evaluation computes bonuses, overtime, and salary disbursements with penalty deductions for unexcused downtime.

### 2. Predictive Maintenance & Equipment Health
- Real-time tracking of vibration indices, core temperature, and runtime cycles.
- Automated creation of **Emergency Work Orders** when sensor anomalies breach statistical standard deviations.
- Equipment history timelines detailing every maintenance event, component replacement, and assigned technician.

### 3. Multilingual AI Assistant (Gemini)
- Factory context-aware assistant injecting real-time statistics: machine uptime, active work tickets, critical inventory stock, and historical batch yield.
- Fully multilingual: Prompting and answers supported in **English**, **Hindi (हिंदी)**, and **Marathi (मराठी)**.
- Integrated **Text-to-Speech (TTS)** voice synthesis for natural spoken audio responses.
- Resilient model fallback ladder across Gemini tiers in case of rate limits.

### 4. Dual Database Router & Offline Resilience
- Seamless transition between cloud PostgreSQL (Supabase) and local SQLite.
- Custom middleware detects database timeout or network partition, transparently redirecting non-destructive queries to local storage to maintain plant operations.

### 5. Role-Based Access & Supervisor Control
- Fine-grained role hierarchy:
  - 👑 **Admin (`AD`)**: Plant-wide configuration, access control, database sync.
  - 👔 **Production Manager (`PM`)**: Target assignment, overall yield KPI monitoring.
  - 👷 **Supervisor (`SU`)**: Shift roster management, employee allocation, attendance.
  - 🔨 **Employee (`EM`)**: Machine work logging, raw material usage, payroll views.
  - 🚚 **Logistics (`LO`)**: Finished goods dispatches, raw material receiving.
  - 🔧 **Maintenance (`MA`)**: Work orders, sensor calibration, machine repair logs.

---

## 📁 Project Directory Structure

```text
PharmaERP/
├── apps/
│   ├── accounts/              # User models, authentication, KYC, shifts
│   ├── ai_chat/               # Gemini AI chatbot, contextual prompts, TTS
│   ├── inventory/             # Warehouse inventory, stock management
│   ├── logistics/             # Transport tracking and dispatches
│   ├── maintenance/           # Equipment telemetry, tickets, APScheduler
│   └── production/            # Work orders, logs, ML scheduler, decision engine
├── daily_reports/             # Auto-generated daily factory summary text files
├── pharma_erp/                # Django root settings, DB router, middleware, URLs
├── static/                    # CSS, JavaScript, vendor assets
│   └── css/
│       ├── kyc.css
│       └── style.css
├── templates/                 # Production-grade responsive HTML5 UI templates
│   ├── ai_chat.html           # Floating & standalone AI conversational UI
│   ├── dashboard.html         # Executive overview & KPIs
│   ├── equipment.html         # Machine telemetry & maintenance board
│   ├── inventory.html         # Warehouse levels & stock replenishment
│   ├── login.html             # Role-based login portal
│   ├── production.html        # Daily production tracking & batch logs
│   ├── supervisor.html        # Worker allocation & shift rosters
│   └── ...
├── .env.example               # Template environment configuration
├── .gitignore                 # Excludes venv, pycache, sensitive keys
├── db.sqlite3                 # Local fallback / development SQLite database
├── manage.py                  # Django CLI entrypoint
├── requirements.txt           # Python dependency specification
├── seed_data.py               # Database seeder (users, machines, logs)
└── daily_reporter.py          # Daily report generation background task
```

---

## ⚙️ Prerequisites

- **Python**: Version `3.10` or higher (`3.11` / `3.12` recommended)
- **Git**: Installed and configured on your system
- **PostgreSQL / Supabase** (Optional for production, SQLite is pre-configured for local testing)
- **Google Gemini API Key** (Optional, required only for AI chatbot features)

---

## 🛠 Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/satvikbarhate45-star/FactoryERP.git
cd FactoryERP
```

### 2. Create and Activate a Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 🔐 Environment Variables

Create a `.env` file in the project root by copying the template:

```bash
# Windows PowerShell
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

Edit `.env` to configure your settings:

```ini
# Django Secret Key & Debug Mode
SECRET_KEY=your-secure-secret-key-here
DEBUG=False
ALLOWED_HOSTS=.onrender.com,localhost,127.0.0.1

# Database (Supabase PostgreSQL pooler string):
DATABASE_URL=postgresql://postgres.[REF]:[PASS]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require

# Hugging Face ML Pipeline (Anomaly Detection & Root-Cause Analysis)
HUGGINGFACE_API_KEY=hf_your_token_here

# AI Chatbot & Voice Synthesis (Google Gemini)
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 🚀 Deployment on Render

### Render Web Service Configuration:
1. **Repository**: Link `https://github.com/satvikbarhate45-star/FactoryERP.git`
2. **Environment**: `Python`
3. **Build Command**:
   ```bash
   ./build.sh
   # (or: pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate)
   ```
4. **Start Command**:
   ```bash
   gunicorn pharma_erp.wsgi:application
   ```
5. **Environment Variables on Render Dashboard**:
   - `DATABASE_URL`: `postgresql://postgres.[REF]:[PASS]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require`
   - `HUGGINGFACE_API_KEY`: `hf_...` (or `HF_TOKEN`)
   - `SECRET_KEY`: `your-secure-django-secret-key`
   - `DEBUG`: `False`
   - `ALLOWED_HOSTS`: `.onrender.com`


---

## 💾 Database Setup & Mock Data Seeding

### 1. Run Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 2. Seed Initial Factory Data
To populate the database with machines, realistic production history, shifts, inventory stocks, and users:

```bash
python seed_data.py
```

*Optional comprehensive mock data generator:*
```bash
python generate_all_modules_data.py
```

---

## 🏃 Running the Application

### 1. Start the Django Development Server
```bash
python manage.py runserver
```
Visit the application in your browser at: **`http://127.0.0.1:8000/`**

### 2. Start the Background Scheduler (APScheduler)
In a separate terminal, run the scheduler for automated daily imputation and machine monitoring:
```bash
python manage.py runapscheduler
```

---

## 👤 Default Demo Credentials

When seeded with `seed_data.py`, the following demo accounts are available:

| Role | Username | Password | Access Area |
| :--- | :--- | :--- | :--- |
| **Admin** | `Aniket` | `Aniket@123` | Full System & Admin Portal (`/admin/`) |
| **Production Manager** | `ProdManager` | `password123` | Dashboard & Production Targets (`/production/`) |
| **Supervisor** | `Supervisor1` | `password123` | Supervisor Shift Board (`/supervisor/`) |
| **Employee** | `Worker1` | `password123` | Work Logging & Shifts (`/`) |

---

## 🌐 API & URL Routing

| Route | View / App | Description |
| :--- | :--- | :--- |
| `/` | `apps.accounts` | Authentication, KYC verification, shift assignments |
| `/production/` | `apps.production` | Production logs, yield calculations, batch tracking |
| `/supervisor/` | `apps.production` | Employee allocation, shift management, live attendance |
| `/maintenance/`| `apps.maintenance` | Equipment telemetry, predictive alerts, work orders |
| `/inventory/`  | `apps.inventory` | Warehouse stock monitoring, raw material receiving |
| `/ai/`         | `apps.ai_chat` | Multilingual Gemini conversational assistant & TTS audio |
| `/admin/`      | `django.contrib.admin` | Django administration portal |

---

## 📄 License & Attribution

Developed for modern continuous pharmaceutical manufacturing operations.  
Licensed under the [MIT License](LICENSE).
