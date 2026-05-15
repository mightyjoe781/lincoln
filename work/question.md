# Python Developer — Invoice & Bank Statement Parsing API

## Objective

Build a production-grade backend service using FastAPI that allows users to upload PDF invoices and CSV bank statements, automatically extract structured financial data, store it in a relational database, and expose robust APIs for retrieval, modification, and search.

The system should simulate real-world backend engineering challenges, including:

- Inconsistent input formats

- Partial or missing data

- Parsing failures

- Error handling

- Scalable architecture design

The goal is to evaluate the candidate’s ability to design and implement a practical, maintainable, and extensible backend system — not just a basic CRUD application.

---

# Business Context

Organizations receive financial documents from multiple vendors and banks in inconsistent formats. Manual processing is slow, repetitive, and error-prone.

This system acts as an internal tool to:

- Standardize incoming financial documents

- Extract structured data automatically

- Persist normalized records

- Enable downstream reporting and analysis

---

# Scope of Work

The candidate is expected to design and implement a backend service that:

- Accepts file uploads (PDF and CSV)

- Extracts relevant financial data

- Stores structured data in a database

- Provides APIs for managing and querying data

- Handles real-world inconsistencies and failures gracefully

- Is containerized and deployable in a cloud environment

---

# Functional Requirements

## 1. File Upload

Support:

- PDF invoices

- CSV bank statements

Requirements:

- Validate file size and type

- Handle duplicate uploads

- Store uploaded files safely

- Maintain upload metadata

---

## 2. Data Parsing

Extract structured information such as:

- Vendor name

- Invoice or transaction date

- Amount

- Currency

- Line items

- Transaction descriptions

Requirements:

- Handle multiple document formats

- Support partially missing fields

- Normalize:

  - Date formats

  - Currency formats

  - Numeric values

---

## 3. Data Storage

Use PostgreSQL as the primary database.

Requirements:

- Design a normalized schema

- Store parsed financial records

- Track:

  - Processing status

  - Parsing errors

  - Upload metadata

  - Audit timestamps

---

## 4. APIs (Async)

Build asynchronous REST APIs using FastAPI.

Required endpoints:

- Upload documents

- Retrieve uploaded documents

- Fetch parsed data

- Update metadata

- Delete records

---

## 5. Search & Filtering

Support filtering by:

- Vendor name

- Date range

- Amount range

- Currency

- Document type

- Processing status

Optional enhancements:

- Pagination

- Sorting

- Full-text search

---

## 6. Error Handling

Requirements:

- Graceful handling of parsing failures

- Meaningful API error responses

- Logging of failures and exceptions

- Retry-safe processing behavior

---

# Non-Functional Requirements

The system should:

- Follow clean architecture principles

- Be modular and maintainable

- Follow REST API best practices

- Use environment variables for configuration

- Include input validation and basic security practices

- Provide logging and basic observability

- Be easy to extend with new parsers

---

# Suggested Architecture

Recommended stack:

| Layer | Suggested Technology |

|---|---|

| API Layer | FastAPI |

| ORM | SQLAlchemy |

| Database | PostgreSQL |

| Containerization | Docker |

| Async Processing (Optional) | Celery + Redis |

Suggested components:

- API service

- Parsing service

- Database layer

- Background worker (optional)

- File storage layer

- Logging & monitoring

---

# Deployment Requirements

Provide:

- Docker Compose or deployment YAML

- PostgreSQL integration

- Environment-based configuration

- Deployment plan for cloud platforms such as:

  - AWS

  - GCP

  - Azure

  - Render

Optional:

- Live deployment URL

- CI/CD setup

---

# Evaluation Criteria

Candidates will be evaluated on:

- Code quality and structure

- API design and usability

- Database schema design

- Robustness of parsing logic

- Error handling quality

- Documentation clarity

- Deployment readiness

- Handling of edge cases and messy inputs

---

# Submission Requirements

Please include:

1. GitHub repository or zipped source code

2. README with setup instructions

3. API documentation or Swagger screenshots

4. Deployment plan

5. Database schema explanation

6. Sample input files

7. AI tool chat history

8. Known limitations and assumptions

---

# Bonus Points

Additional credit for:

- Unit tests and code coverage

- Background processing support

- Authentication placeholder or JWT setup

- Improved logging and observability

- Deduplication logic

- Performance optimizations

- Scalable parsing architecture

- Rate limiting

- Async file processing pipeline