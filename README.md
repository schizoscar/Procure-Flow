<p align="center">
  <img src="assets/logo.png" alt="ProcureFlow Logo" width="300"/>
</p>

<h1 align="center">ProcureFlow</h1>

<p align="center">
  <strong>Web-Based Procurement & Workflow Automation System</strong>
</p>

<p align="center">
  Built with Flask, Python, PostgreSQL, and deployed on Render
</p>

---

## Overview

**ProcureFlow** is a web-based procurement automation system designed to replace manual, spreadsheet-driven purchasing workflows with a centralized, structured, and scalable platform.

It streamlines the end-to-end procurement lifecycle — from purchase requisition creation to supplier coordination, quotation handling, and approval tracking — within a single system.

The goal is to reduce operational friction, improve traceability, and automate repetitive procurement tasks commonly found in business environments.

---

## Key Features

### Procurement Workflow Automation
- Create and manage Purchase Requisitions (PRs)
- Structured multi-item PR creation with dynamic fields
- Automated task-based workflow generation

### Supplier Management
- Centralized supplier database
- Category-based supplier classification
- Supplier assignment per procurement task

### Quotation & Comparison System
- Capture supplier quotations
- Store and manage response data
- Support structured price comparison workflows

### Email Automation
- Automated supplier email distribution
- Follow-up tracking system
- Email logging for audit purposes

### File & Document Handling
- Upload and attach supporting documents
- Store supplier quotations and certificates
- Link files to tasks, suppliers, and PR items

### Role-Based Access Control
- Secure authentication system
- Multi-user role separation (admin/user)
- Session-based access control

### Data Management
- Full CRUD operations for procurement entities
- Relational database structure (PostgreSQL)
- Historical procurement tracking

---

## System Architecture

```text
User Login
    │
    ▼
Create Purchase Requisition (PR)
    │
    ▼
Add Items & Specifications
    │
    ▼
Assign Suppliers by Category
    │
    ▼
Automated Email Distribution
    │
    ▼
Supplier Responses & Quotations
    │
    ▼
Comparison & Evaluation
    │
    ▼
Procurement Record Storage
```
---

## Tech Stack

**Backend**
- Python
- Flask
- SQLAlchemy

**Frontend**
- HTML
- CSS
- JavaScript

**Database**
- PostgreSQL

**Infrastructure**
- Render (Web Service + Managed PostgreSQL)

---

## Core Modules

- Authentication & Session Management
- Procurement Request System
- Supplier Management System
- Email Automation Engine
- File Management System
- Task & Workflow Engine
- Reporting & Data Tracking

---

## Problem It Solves

Traditional procurement processes often rely on:
- Excel spreadsheets
- Email chains
- Manual supplier tracking
- Lack of centralized audit trails

ProcureFlow solves this by:
- Centralizing procurement data
- Automating supplier communication
- Structuring approval workflows
- Improving traceability and accountability

---

## Deployment

Live system deployed on Render:
- Backend: Flask Web Service
- Database: Managed PostgreSQL
- Environment-based configuration (dev / production)
