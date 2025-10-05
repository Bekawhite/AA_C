import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import math
import hashlib
import secrets
import string
import logging
import smtplib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import uuid
import os
from dataclasses import dataclass
from contextlib import contextmanager
import html
import re
import threading
import time
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enhanced Configuration Classes
@dataclass
class DatabaseConfig:
    url: str = os.getenv('DATABASE_URL', 'sqlite:///hospital_referral.db')
    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle: int = 3600

@dataclass
class SMTPConfig:
    server: str = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    port: int = int(os.getenv('SMTP_PORT', 587))
    username: Optional[str] = os.getenv('SMTP_USERNAME')
    password: Optional[str] = os.getenv('SMTP_PASSWORD')
    use_tls: bool = True

@dataclass
class MapConfig:
    default_latitude: float = -0.0916
    default_longitude: float = 34.7680
    default_zoom: int = 10
    google_maps_api_key: Optional[str] = os.getenv('GOOGLE_MAPS_API_KEY', '')

@dataclass
class CostConfig:
    fuel_price_per_liter: float = 180.0
    average_fuel_consumption: float = 0.12  # liters per km
    base_operating_cost_per_km: float = 50.0
    fuel_tank_capacity: float = 80.0

@dataclass
class AppConfig:
    page_title: str = "Kisumu County Hospital Referral System"
    page_icon: str = "🏥"
    layout: str = "wide"
    notification_check_interval: int = 30
    location_update_interval: int = 10
    secret_key: str = 'dev-secret-key-change-in-production'

class Config:
    database = DatabaseConfig()
    smtp = SMTPConfig()
    maps = MapConfig()
    costs = CostConfig()
    app = AppConfig()

# Database Models and Setup (Enhanced with cost tracking)
import sqlalchemy as sa
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, Text, Boolean, Float, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.pool import StaticPool

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = 'users'
    
    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    hospital = Column(String(255), nullable=False)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)

class Patient(Base):
    __tablename__ = 'patients'
    
    patient_id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String(10), nullable=False)
    condition = Column(String(255), nullable=False)
    referring_hospital = Column(String(255), nullable=False)
    receiving_hospital = Column(String(255), nullable=False)
    referring_physician = Column(String(100), nullable=False)
    receiving_physician = Column(String(100))
    notes = Column(Text)
    vital_signs = Column(JSON)
    medical_history = Column(Text)
    current_medications = Column(Text)
    allergies = Column(Text)
    referral_time = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String(50), default='Referred', index=True)
    assigned_ambulance = Column(String, ForeignKey('ambulances.ambulance_id'))
    created_by = Column(String, ForeignKey('users.id'))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    referring_hospital_lat = Column(Float)
    referring_hospital_lng = Column(Float)
    receiving_hospital_lat = Column(Float)
    receiving_hospital_lng = Column(Float)
    pickup_notification_sent = Column(Boolean, default=False)
    enroute_notification_sent = Column(Boolean, default=False)
    
    # Enhanced: Cost tracking fields
    trip_distance = Column(Float)
    trip_fuel_cost = Column(Float)
    trip_cost_savings = Column(Float, default=0.0)
    actual_distance_covered = Column(Float)  # Track actual distance covered

class Ambulance(Base):
    __tablename__ = 'ambulances'
    
    ambulance_id = Column(String, primary_key=True, default=generate_uuid)
    current_location = Column(String(255))
    latitude = Column(Float, index=True)
    longitude = Column(Float, index=True)
    status = Column(String(50), default='Available', index=True)
    driver_name = Column(String(100), nullable=False)
    driver_contact = Column(String(20))
    current_patient = Column(String, ForeignKey('patients.patient_id'))
    destination = Column(String(255))
    route = Column(JSON)
    start_time = Column(DateTime)
    current_step = Column(Integer, default=0)
    mission_complete = Column(Boolean, default=False)
    estimated_arrival = Column(DateTime)
    last_location_update = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Enhanced: Fuel and cost tracking
    fuel_level = Column(Float, default=100.0)
    fuel_consumption_rate = Column(Float, default=0.12)
    total_fuel_cost = Column(Float, default=0.0)
    total_distance_traveled = Column(Float, default=0.0)
    cost_savings = Column(Float, default=0.0)
    ambulance_type = Column(String(50), default='Basic Life Support')
    equipment = Column(Text)

class Referral(Base):
    __tablename__ = 'referrals'
    
    id = Column(String, primary_key=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey('patients.patient_id'), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String(50), default='Ambulance Dispatched')
    ambulance_id = Column(String, ForeignKey('ambulances.ambulance_id'))
    created_by = Column(String, ForeignKey('users.id'))

class HandoverForm(Base):
    __tablename__ = 'handover_forms'
    
    id = Column(String, primary_key=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey('patients.patient_id'), nullable=False, index=True)
    patient_name = Column(String(100))
    age = Column(Integer)
    gender = Column(String(10))
    condition = Column(String(255))
    referring_hospital = Column(String(255))
    receiving_hospital = Column(String(255))
    referring_physician = Column(String(100))
    receiving_physician = Column(String(100))
    transfer_time = Column(DateTime, default=datetime.utcnow)
    vital_signs = Column(JSON)
    medical_history = Column(Text)
    current_medications = Column(Text)
    allergies = Column(Text)
    notes = Column(Text)
    ambulance_id = Column(String)
    created_by = Column(String, ForeignKey('users.id'))
    # Enhanced: Add cost tracking to handover
    distance_covered = Column(Float)
    fuel_cost = Column(Float)
    total_cost = Column(Float)

class Communication(Base):
    __tablename__ = 'communications'
    
    id = Column(String, primary_key=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey('patients.patient_id'), index=True)
    ambulance_id = Column(String, ForeignKey('ambulances.ambulance_id'), index=True)
    sender = Column(String(100), nullable=False)
    receiver = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    message_type = Column(String(50))
    sender_id = Column(String, ForeignKey('users.id'))

class LocationUpdate(Base):
    __tablename__ = 'location_updates'
    
    id = Column(String, primary_key=True, default=generate_uuid)
    ambulance_id = Column(String, ForeignKey('ambulances.ambulance_id'), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    location_name = Column(String(255))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    patient_id = Column(String, ForeignKey('patients.patient_id'))

# Create indexes
Index('idx_patient_status', Patient.status)
Index('idx_ambulance_status', Ambulance.status)
Index('idx_referral_timestamp', Referral.timestamp)
Index('idx_communication_timestamp', Communication.timestamp)
Index('idx_location_timestamp', LocationUpdate.timestamp)

# Database setup
engine = create_engine(
    Config.database.url,
    connect_args={"check_same_thread": False} if "sqlite" in Config.database.url else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

# Enhanced Authentication System
class Authentication:
    def __init__(self):
        self.session = st.session_state
        if 'authenticated' not in self.session:
            self.session.authenticated = False
        if 'user' not in self.session:
            self.session.user = None

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self._hash_password(plain_password) == hashed_password

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        try:
            with session_scope() as session:
                user = session.query(User).filter(
                    User.username == username,
                    User.is_active == True
                ).first()
                
                if user and self._verify_password(password, user.password_hash):
                    user.last_login = datetime.utcnow()
                    session.commit()
                    
                    user_data = {
                        'id': user.id,
                        'username': user.username,
                        'email': user.email,
                        'role': user.role,
                        'hospital': user.hospital,
                        'name': user.name,
                        'last_login': user.last_login
                    }
                    
                    return user_data
            
            return None
            
        except Exception as e:
            st.error(f"Authentication error: {str(e)}")
            return None

    def register_user(self, user_data: Dict[str, Any]) -> bool:
        try:
            with session_scope() as session:
                existing_user = session.query(User).filter(
                    User.username == user_data['username']
                ).first()
                
                if existing_user:
                    st.error("Username already exists")
                    return False
                
                new_user = User(
                    username=user_data['username'],
                    email=user_data['email'],
                    password_hash=self._hash_password(user_data['password']),
                    role=user_data['role'],
                    hospital=user_data['hospital'],
                    name=user_data['name']
                )
                
                session.add(new_user)
                session.commit()
                
                st.success(f"User {user_data['username']} created successfully")
                return True
                
        except Exception as e:
            st.error(f"Registration error: {str(e)}")
            return False

    def setup_auth_ui(self):
        st.sidebar.title("🔐 Authentication")
        
        if not self.session.authenticated:
            tab1, tab2 = st.sidebar.tabs(["Login", "Register"])
            
            with tab1:
                self._login_form()
            with tab2:
                self._register_form()
        else:
            self._logout_section()

    def _login_form(self):
        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            
            if st.form_submit_button("Login", use_container_width=True):
                if not username or not password:
                    st.error("Please enter both username and password")
                    return
                
                user = self.authenticate_user(username, password)
                if user:
                    self.session.authenticated = True
                    self.session.user = user
                    st.sidebar.success(f"Welcome {user['role']}!")
                    st.rerun()
                else:
                    st.error("Invalid credentials")

    def _register_form(self):
        if not self.session.authenticated:
            st.info("Please login as admin to register new users")
            return
            
        if self.session.user['role'] != 'Admin':
            st.warning("Only administrators can register new users")
            return
            
        with st.form("register_form"):
            st.subheader("Register New User")
            
            username = st.text_input("Username")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            name = st.text_input("Full Name")
            role = st.selectbox("Role", ["Admin", "Hospital Staff", "Ambulance Driver"])
            hospital = st.selectbox("Hospital", self._get_hospital_options())
            
            if st.form_submit_button("Register User", use_container_width=True):
                if not all([username, email, password, name]):
                    st.error("Please fill all fields")
                    return
                    
                if password != confirm_password:
                    st.error("Passwords do not match")
                    return
                    
                user_data = {
                    'username': username,
                    'email': email,
                    'password': password,
                    'role': role,
                    'hospital': hospital,
                    'name': name
                }
                
                if self.register_user(user_data):
                    st.rerun()

    def _get_hospital_options(self):
        return list(HOSPITAL_LOCATIONS.keys())

    def _logout_section(self):
        st.sidebar.success(f"Logged in as: {self.session.user['name']}")
        st.sidebar.write(f"**Role:** {self.session.user['role']}")
        st.sidebar.write(f"**Hospital:** {self.session.user['hospital']}")
        
        if st.sidebar.button("Logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    def require_auth(self, roles: Optional[list] = None) -> bool:
        if not self.session.authenticated:
            st.warning("Please login to access this page")
            return False
            
        if roles and self.session.user['role'] not in roles:
            st.error(f"Access denied. Required roles: {', '.join(roles)}")
            return False
            
        return True

    def initialize_default_users(self):
        try:
            with session_scope() as session:
                user_count = session.query(User).count()
                
                if user_count == 0:
                    default_users = [
                        {
                            'username': 'admin',
                            'email': 'admin@kisumu.gov',
                            'password': 'admin123',
                            'role': 'Admin',
                            'hospital': 'All Facilities',
                            'name': 'System Administrator'
                        },
                        {
                            'username': 'hospital_staff',
                            'email': 'staff@joortrh.go.ke',
                            'password': 'staff123',
                            'role': 'Hospital Staff',
                            'hospital': 'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
                            'name': 'Hospital Staff Member'
                        },
                        {
                            'username': 'driver',
                            'email': 'driver@kisumu.gov',
                            'password': 'driver123',
                            'role': 'Ambulance Driver',
                            'hospital': 'Ambulance Service',
                            'name': 'Ambulance Driver'
                        },
                        {
                            'username': 'kisumu_staff',
                            'email': 'staff@kisumuhospital.go.ke',
                            'password': 'kisumu123',
                            'role': 'Hospital Staff',
                            'hospital': 'Kisumu County Referral Hospital (KCRH)',
                            'name': 'Kisumu County Hospital Staff'
                        }
                    ]
                    
                    for user_data in default_users:
                        user = User(
                            username=user_data['username'],
                            email=user_data['email'],
                            password_hash=self._hash_password(user_data['password']),
                            role=user_data['role'],
                            hospital=user_data['hospital'],
                            name=user_data['name']
                        )
                        session.add(user)
                    
                    session.commit()
                    logger.info("Default users initialized")
                    
        except Exception as e:
            logger.error(f"Error initializing default users: {str(e)}")

# Updated Hospital Locations with accurate coordinates
HOSPITAL_LOCATIONS = {
    "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)": {
        "lat": -0.08864, 
        "lng": 34.7714,
        "address": "Off Kisumu-Bondo Road, Kisumu"
    },
    "Kisumu County Referral Hospital (KCRH)": {
        "lat": -0.10129, 
        "lng": 34.75598,
        "address": "Kisumu City Center"
    },
    "Lumumba Sub-County Hospital": {
        "lat": -0.09968, 
        "lng": 34.76599,
        "address": "Lumumba Road, Kisumu"
    },
    "Ahero County Hospital": {
        "lat": -0.17321, 
        "lng": 34.92367,
        "address": "Ahero Town, Kisumu"
    },
    "Kombewa District Hospital": {
        "lat": -0.10345, 
        "lng": 34.51792,
        "address": "Kombewa, Kisumu West"
    },
    "Masogo Sub-County Hospital": {
        "lat": -0.09843, 
        "lng": 35.00522,
        "address": "Masogo, Nyang'oma"
    },
    "Chulaimbo Sub-District Hospital": {
        "lat": -0.03785, 
        "lng": 34.63821,
        "address": "Chulaimbo"
    },
    "Ober Kamoth Health Centre": {
        "lat": -0.11518, 
        "lng": 34.60952,
        "address": "Ober Kamoth"
    },
    "Nyakach Sub-County Hospital": {
        "lat": -0.31293, 
        "lng": 34.93741,
        "address": "Pap Onditi, Nyakach"
    },
    "Rabuor Sub-County Hospital": {
        "lat": -0.15333, 
        "lng": 34.8299,
        "address": "Rabuor"
    },
    "Muhoroni Sub-District Hospital": {
        "lat": -0.15112, 
        "lng": 35.20573,
        "address": "Muhoroni Town"
    },
    "Miranga Sub-District Hospital": {
        "lat": -0.09883, 
        "lng": 35.0495,
        "address": "Miranga, Seme"
    },
    "Victoria Sub-District Hospital": {
        "lat": -0.11147, 
        "lng": 34.75107,
        "address": "Victoria, Kisumu"
    },
    "Miwani Health Centre": {
        "lat": -0.05023, 
        "lng": 34.97964,
        "address": "Miwani, Muhoroni"
    },
    "Nyahera Sub-District Hospital": {
        "lat": -0.03495, 
        "lng": 34.71281,
        "address": "Nyahera, Kisumu West"
    },
    "Nyamware Health Centre": {
        "lat": -0.16268, 
        "lng": 34.80765,
        "address": "Nyamware, Kobura"
    },
    "Nyamarimba Sub-County Hospital": {
        "lat": -0.371554, 
        "lng": 34.90891,
        "address": "Nyakach"
    },
    "Nyang'oma Sub-County Hospital": {
        "lat": -0.145931, 
        "lng": 35.044567,
        "address": "Nyang'oma, Muhoroni"
    },
    "Ojola Sub-County Hospital": {
        "lat": -0.06627, 
        "lng": 34.64551,
        "address": "Kisumu West"
    },
    "Manyuanda Sub-County Hospital": {
        "lat": -0.14141, 
        "lng": 34.46953,
        "address": "West Seme, Seme"
    },
    "Migosi Health Centre": {
        "lat": -0.07607, 
        "lng": 34.78327,
        "address": "Migosi"
    },
    "Nyalenda Health Centre": {
        "lat": -0.1226, 
        "lng": 34.75211,
        "address": "Nyalenda"
    },
    "Migere Health Centre": {
        "lat": -0.110731, 
        "lng": 35.10164,
        "address": "Migere, Muhoroni"
    },
    "Mashambani Health Centre": {
        "lat": -0.08145, 
        "lng": 35.15148,
        "address": "Chemelil, Muhoroni"
    },
    "Mbaka Oromo Dispensary": {
        "lat": -0.01469, 
        "lng": 34.63468,
        "address": "Mbaka Oromo"
    },
    "Nduru Kadero Dispensary": {
        "lat": -0.06836, 
        "lng": 34.46748,
        "address": "Nduru Kadero"
    },
    "Nyabondo Rehabilitation Centre": {
        "lat": -0.38172, 
        "lng": 34.97882,
        "address": "Nyabondo"
    },
    "Nyakongo Dispensary": {
        "lat": -0.20083, 
        "lng": 35.01355,
        "address": "Nyakongo"
    },
    "Nyalunya Dispensary": {
        "lat": -0.11746, 
        "lng": 34.80916,
        "address": "Nyalunya"
    },
    "Milimani Maternity": {
        "lat": -0.1217, 
        "lng": 34.75328,
        "address": "Milimani"
    },
    "Nyangande Health Centre": {
        "lat": -0.20814, 
        "lng": 34.84557,
        "address": "Nyangande"
    },
    "Katito Health Centre": {
        "lat": -0.26973, 
        "lng": 34.97284,
        "address": "Katito"
    },
    "Kodiaga Prison Health Centre": {
        "lat": -0.06211, 
        "lng": 34.70884,
        "address": "Kodiaga"
    },
    "Gita Sub-County Hospital": {
        "lat": -0.02782, 
        "lng": 34.79048,
        "address": "Gita"
    },
    "Kusa Health Centre": {
        "lat": -0.33545, 
        "lng": 34.85203,
        "address": "Kusa"
    },
    "Sondu Health Centre": {
        "lat": -0.37907, 
        "lng": 35.00111,
        "address": "Sondu"
    }
}

AMBULANCE_DATA = [
    {"ambulance_id": "KBA 453D", "driver_name": "John Omondi", "driver_contact": "254712345678", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBC 217F", "driver_name": "Mary Achieng", "driver_contact": "254723456789", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBD 389G", "driver_name": "Paul Otieno", "driver_contact": "254735678901", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBE 142H", "driver_name": "Susan Akinyi", "driver_contact": "254746789012", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBF 561J", "driver_name": "David Owino", "driver_contact": "254757890123", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBG 774K", "driver_name": "James Okoth", "driver_contact": "254768901234", "status": "Available", "location": "Kombewa District Hospital", "current_patient": None, "lat": -0.10345, "lng": 34.51792},
    {"ambulance_id": "KBH 238L", "driver_name": "Grace Atieno", "driver_contact": "254779012345", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBJ 965M", "driver_name": "Peter Onyango", "driver_contact": "254789123456", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBK 482N", "driver_name": "Alice Adhiambo", "driver_contact": "254790234567", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBL 751P", "driver_name": "Robert Ochieng", "driver_contact": "254701345678", "status": "Available", "location": "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "current_patient": None, "lat": -0.08864, "lng": 34.7714},
    {"ambulance_id": "KBM 312Q", "driver_name": "Sarah Nyongesa", "driver_contact": "254712456789", "status": "Available", "location": "Kisumu County Referral Hospital (KCRH)", "current_patient": None, "lat": -0.10129, "lng": 34.75598},
    {"ambulance_id": "KBN 864R", "driver_name": "Michael Odhiambo", "driver_contact": "254723567890", "status": "Available", "location": "Kisumu County Referral Hospital (KCRH)", "current_patient": None, "lat": -0.10129, "lng": 34.75598},
    {"ambulance_id": "KBP 459S", "driver_name": "Elizabeth Awuor", "driver_contact": "254735678901", "status": "Available", "location": "Kisumu County Referral Hospital (KCRH)", "current_patient": None, "lat": -0.10129, "lng": 34.75598},
    {"ambulance_id": "KBQ 287T", "driver_name": "Daniel Omondi", "driver_contact": "254746789012", "status": "Available", "location": "Kisumu County Referral Hospital (KCRH)", "current_patient": None, "lat": -0.10129, "lng": 34.75598},
    {"ambulance_id": "KBR 913U", "driver_name": "Lucy Anyango", "driver_contact": "254757890123", "status": "Available", "location": "Kisumu County Referral Hospital (KCRH)", "current_patient": None, "lat": -0.10129, "lng": 34.75598},
    {"ambulance_id": "KBS 506V", "driver_name": "Brian Ouma", "driver_contact": "254768901234", "status": "Available", "location": "Kisumu County Referral Hospital (KCRH)", "current_patient": None, "lat": -0.10129, "lng": 34.75598},
    {"ambulance_id": "KBT 678W", "driver_name": "Patricia Adongo", "driver_contact": "254779012345", "status": "Available", "location": "Kisumu County Referral Hospital (KCRH)", "current_patient": None, "lat": -0.10129, "lng": 34.75598},
    {"ambulance_id": "KBU 134X", "driver_name": "Samuel Owuor", "driver_contact": "254789123456", "status": "Available", "location": "Ahero County Hospital", "current_patient": None, "lat": -0.17321, "lng": 34.92367},
    {"ambulance_id": "KBV 925Y", "driver_name": "Rebecca Aoko", "driver_contact": "254790234567", "status": "Available", "location": "Ahero County Hospital", "current_patient": None, "lat": -0.17321, "lng": 34.92367},
    {"ambulance_id": "KBX 743Z", "driver_name": "Kevin Onyango", "driver_contact": "254701345678", "status": "Available", "location": "Ahero County Hospital", "current_patient": None, "lat": -0.17321, "lng": 34.92367}
]

# Enhanced Service Classes
class DatabaseService:
    def __init__(self):
        self.engine = engine
        
    @contextmanager
    def get_session(self):
        session = SessionLocal()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two coordinates in kilometers using Haversine formula"""
        R = 6371  # Earth radius in kilometers
        
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat/2) * math.sin(dlat/2) + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon/2) * math.sin(dlon/2))
        
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        return round(distance, 2)
    
    def find_nearest_ambulance(self, hospital_lat: float, hospital_lng: float, min_fuel_level: float = 20.0):
        """Find the nearest available ambulance with sufficient fuel"""
        with self.get_session() as session:
            available_ambulances = session.query(Ambulance).filter(
                Ambulance.status == 'Available',
                Ambulance.fuel_level >= min_fuel_level
            ).all()
            
            if not available_ambulances:
                return None
            
            nearest_ambulance = None
            min_distance = float('inf')
            
            for ambulance in available_ambulances:
                if ambulance.latitude is not None and ambulance.longitude is not None:
                    distance = self.calculate_distance(
                        hospital_lat, hospital_lng, 
                        ambulance.latitude, ambulance.longitude
                    )
                    if distance < min_distance:
                        min_distance = distance
                        nearest_ambulance = ambulance
            
            return nearest_ambulance

class CostCalculationService:
    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
    
    def calculate_trip_cost(self, distance_km: float, fuel_consumption_rate: Optional[float] = None) -> Dict[str, float]:
        if fuel_consumption_rate is None:
            fuel_consumption_rate = Config.costs.average_fuel_consumption
        
        fuel_used = distance_km * fuel_consumption_rate
        fuel_cost = fuel_used * Config.costs.fuel_price_per_liter
        operating_cost = distance_km * Config.costs.base_operating_cost_per_km
        total_cost = fuel_cost + operating_cost
        
        return {
            'distance_km': distance_km,
            'fuel_used_liters': round(fuel_used, 2),
            'fuel_cost_ksh': round(fuel_cost, 2),
            'operating_cost_ksh': round(operating_cost, 2),
            'total_cost_ksh': round(total_cost, 2)
        }
    
    def calculate_potential_savings(self, actual_distance: float, alternative_distance: float) -> float:
        """Calculate potential savings from efficient routing"""
        actual_cost = self.calculate_trip_cost(actual_distance)
        alternative_cost = self.calculate_trip_cost(alternative_distance)
        
        savings = alternative_cost['total_cost_ksh'] - actual_cost['total_cost_ksh']
        return max(0, savings)
    
    def update_ambulance_costs(self, ambulance_id: str, distance_km: float) -> Optional[Dict]:
        """Update ambulance cost tracking after a trip"""
        with self.db_service.get_session() as session:
            ambulance = session.query(Ambulance).filter(
                Ambulance.ambulance_id == ambulance_id
            ).first()
            
            if ambulance:
                trip_cost = self.calculate_trip_cost(distance_km, ambulance.fuel_consumption_rate)
                
                ambulance.total_distance_traveled += distance_km
                ambulance.total_fuel_cost += trip_cost['fuel_cost_ksh']
                
                # Calculate potential savings (15% of total cost as efficiency savings)
                potential_savings = trip_cost['total_cost_ksh'] * 0.15
                ambulance.cost_savings += potential_savings
                
                # Update fuel level based on distance covered
                fuel_used = distance_km * ambulance.fuel_consumption_rate
                fuel_used_percentage = (fuel_used / Config.costs.fuel_tank_capacity) * 100
                ambulance.fuel_level = max(0, ambulance.fuel_level - fuel_used_percentage)
                
                session.commit()
                return trip_cost
            
            return None

# Enhanced Notification Service with Automatic Messages
class NotificationService:
    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
    
    def send_automated_notification(self, notification_type: str, data: Dict) -> bool:
        try:
            if notification_type == 'referral_created':
                return self._send_referral_created_notification(data)
            elif notification_type == 'ambulance_assigned':
                return self._send_ambulance_assigned_notification(data)
            elif notification_type == 'driver_assignment':
                return self._send_driver_assignment_notification(data)
            elif notification_type == 'patient_picked_up':
                return self._send_patient_picked_up_notification(data)
            elif notification_type == 'arrival_notification':
                return self._send_arrival_notification(data)
            else:
                return True
                
        except Exception as e:
            logger.error(f"Error sending automated notification: {str(e)}")
            return False
    
    def _send_referral_created_notification(self, data: Dict) -> bool:
        patient = data['patient']
        
        with self.db_service.get_session() as session:
            comm = Communication(
                patient_id=patient.patient_id,
                sender='System',
                receiver=patient.receiving_hospital,
                message=f"New referral for {patient.name} from {patient.referring_hospital}",
                message_type='auto_referral_created'
            )
            session.add(comm)
            session.commit()
        
        return True
    
    def _send_ambulance_assigned_notification(self, data: Dict) -> bool:
        patient = data['patient']
        ambulance = data['ambulance']
        
        with self.db_service.get_session() as session:
            comm = Communication(
                patient_id=patient.patient_id,
                ambulance_id=ambulance.ambulance_id,
                sender='System',
                receiver=patient.receiving_hospital,
                message=f"Ambulance {ambulance.ambulance_id} assigned to patient {patient.name}",
                message_type='auto_ambulance_assigned'
            )
            session.add(comm)
            session.commit()
        
        return True
    
    def _send_driver_assignment_notification(self, data: Dict) -> bool:
        """Send automatic notification to driver when assigned to a referral"""
        patient = data['patient']
        ambulance = data['ambulance']
        
        message = f"""
🚑 NEW PATIENT PICKUP ASSIGNMENT

Patient: {patient.name}
Age: {patient.age}
Gender: {patient.gender}
Condition: {patient.condition}
Location: {patient.referring_hospital}
Destination: {patient.receiving_hospital}
Referring Physician: {patient.referring_physician}

Clinical Notes: {patient.notes or 'None'}
Medical History: {patient.medical_history or 'None'}
Allergies: {patient.allergies or 'None'}

Please proceed to {patient.referring_hospital} immediately for patient pickup.

Estimated Distance: {patient.trip_distance or 'Calculating...'} km
Priority: HIGH

Reply to this message with your ETA or any issues.
        """.strip()
        
        with self.db_service.get_session() as session:
            comm = Communication(
                patient_id=patient.patient_id,
                ambulance_id=ambulance.ambulance_id,
                sender='System',
                receiver=ambulance.driver_name,
                message=message,
                message_type='auto_driver_assignment'
            )
            session.add(comm)
            session.commit()
        
        return True
    
    def _send_patient_picked_up_notification(self, data: Dict) -> bool:
        """Send automatic enroute notification to receiving hospital when patient is picked up"""
        patient = data['patient']
        ambulance = data['ambulance']
        
        message = f"""
🚑 PATIENT PICKED UP - AMBULANCE EN ROUTE

Patient: {patient.name}
Ambulance: {ambulance.ambulance_id}
Driver: {ambulance.driver_name}
Current Location: {ambulance.current_location or 'En route'}
Estimated Arrival: 15-25 minutes

Patient Condition: {patient.condition}
Vital Signs: {patient.vital_signs or 'Stable during transport'}

Please ensure receiving team is ready at emergency entrance.
        """.strip()
        
        with self.db_service.get_session() as session:
            comm = Communication(
                patient_id=patient.patient_id,
                ambulance_id=ambulance.ambulance_id,
                sender='System',
                receiver=patient.receiving_hospital,
                message=message,
                message_type='auto_enroute_notification'
            )
            session.add(comm)
            session.commit()
        
        return True
    
    def _send_arrival_notification(self, data: Dict) -> bool:
        """Send automatic arrival notification when patient arrives at destination"""
        patient = data['patient']
        ambulance = data['ambulance']
        
        message = f"""
✅ PATIENT ARRIVED AT DESTINATION

Patient: {patient.name} has arrived at {patient.receiving_hospital}
Ambulance: {ambulance.ambulance_id}
Arrival Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Trip Distance: {patient.trip_distance or 'Unknown'} km
Fuel Used: {(patient.trip_distance * ambulance.fuel_consumption_rate) if patient.trip_distance else 'Unknown'} L

Patient handed over to receiving team.
Ambulance status: Returning to service
        """.strip()
        
        hospitals = [patient.referring_hospital, patient.receiving_hospital]
        with self.db_service.get_session() as session:
            for hospital in hospitals:
                comm = Communication(
                    patient_id=patient.patient_id,
                    ambulance_id=ambulance.ambulance_id,
                    sender='System',
                    receiver=hospital,
                    message=message,
                    message_type='auto_arrival_notification'
                )
                session.add(comm)
            session.commit()
        
        return True

# Enhanced Referral Service with Cost Tracking & Automatic Notifications
class ReferralService:
    def __init__(self, db_service: DatabaseService, notification_service: NotificationService):
        self.db_service = db_service
        self.notification_service = notification_service
        self.cost_service = CostCalculationService(db_service)
    
    def create_referral(self, patient_data: Dict, user: Dict) -> Optional[Patient]:
        try:
            with self.db_service.get_session() as session:
                required_fields = ['name', 'age', 'gender', 'condition', 'referring_hospital', 'receiving_hospital', 'referring_physician']
                for field in required_fields:
                    if not patient_data.get(field):
                        raise ValueError(f"Missing required field: {field}")
                
                # Get hospital coordinates
                referring_hospital = patient_data['referring_hospital']
                receiving_hospital = patient_data['receiving_hospital']
                
                if referring_hospital in HOSPITAL_LOCATIONS:
                    patient_data['referring_hospital_lat'] = HOSPITAL_LOCATIONS[referring_hospital]['lat']
                    patient_data['referring_hospital_lng'] = HOSPITAL_LOCATIONS[referring_hospital]['lng']
                
                if receiving_hospital in HOSPITAL_LOCATIONS:
                    patient_data['receiving_hospital_lat'] = HOSPITAL_LOCATIONS[receiving_hospital]['lat']
                    patient_data['receiving_hospital_lng'] = HOSPITAL_LOCATIONS[receiving_hospital]['lng']
                
                # Calculate estimated distance and cost
                if (patient_data.get('referring_hospital_lat') and 
                    patient_data.get('referring_hospital_lng') and
                    patient_data.get('receiving_hospital_lat') and 
                    patient_data.get('receiving_hospital_lng')):
                    
                    distance = self.db_service.calculate_distance(
                        patient_data['referring_hospital_lat'],
                        patient_data['referring_hospital_lng'],
                        patient_data['receiving_hospital_lat'],
                        patient_data['receiving_hospital_lng']
                    )
                    
                    cost_estimate = self.cost_service.calculate_trip_cost(distance)
                    patient_data['trip_distance'] = distance
                    patient_data['trip_fuel_cost'] = cost_estimate['total_cost_ksh']
                
                # Remove auto_assign_ambulance from patient_data as it's not a Patient model field
                auto_assign = patient_data.pop('auto_assign_ambulance', False)
                assigned_ambulance = patient_data.pop('assigned_ambulance', None)
                
                # Set referral time to current computer time
                patient_data['referral_time'] = datetime.now()
                
                patient = Patient(**patient_data)
                session.add(patient)
                session.flush()
                
                referral = Referral(
                    patient_id=patient.patient_id,
                    created_by=user['id'],
                    ambulance_id=assigned_ambulance
                )
                session.add(referral)
                session.commit()
                
                # Send automatic notification to receiving hospital
                self.notification_service.send_automated_notification('referral_created', {
                    'patient': patient
                })
                
                # Auto-assign ambulance if selected
                if auto_assign:
                    if self.auto_assign_nearest_ambulance(patient.patient_id):
                        st.success("🚑 Nearest ambulance automatically assigned and driver notified!")
                
                return patient
                
        except Exception as e:
            logger.error(f"Error creating referral: {str(e)}")
            st.error(f"Failed to create referral: {str(e)}")
            return None
    
    def assign_ambulance(self, patient_id: str, ambulance_id: str) -> bool:
        try:
            with self.db_service.get_session() as session:
                patient = session.query(Patient).filter(Patient.patient_id == patient_id).first()
                ambulance = session.query(Ambulance).filter(Ambulance.ambulance_id == ambulance_id).first()
                
                if not patient or not ambulance:
                    st.error("Patient or ambulance not found")
                    return False
                
                if ambulance.status != 'Available':
                    st.error("Ambulance is not available")
                    return False
                
                patient.assigned_ambulance = ambulance_id
                patient.status = 'Ambulance Assigned'
                
                ambulance.status = 'On Transfer'
                ambulance.current_patient = patient_id
                ambulance.destination = patient.receiving_hospital
                
                session.commit()
                
                # Send automatic notifications
                self.notification_service.send_automated_notification('ambulance_assigned', {
                    'patient': patient,
                    'ambulance': ambulance
                })
                
                self.notification_service.send_automated_notification('driver_assignment', {
                    'patient': patient,
                    'ambulance': ambulance
                })
                
                return True
                
        except Exception as e:
            logger.error(f"Error assigning ambulance: {str(e)}")
            st.error(f"Failed to assign ambulance: {str(e)}")
            return False
    
    def auto_assign_nearest_ambulance(self, patient_id: str) -> bool:
        """Automatically assign the nearest available ambulance to a patient"""
        with self.db_service.get_session() as session:
            patient = session.query(Patient).filter(Patient.patient_id == patient_id).first()
            if not patient or not patient.referring_hospital_lat or not patient.referring_hospital_lng:
                st.error("Patient or hospital location data missing")
                return False
            
            nearest_ambulance = self.db_service.find_nearest_ambulance(
                patient.referring_hospital_lat, 
                patient.referring_hospital_lng
            )
            
            if not nearest_ambulance:
                st.error("No available ambulances with sufficient fuel")
                return False
            
            patient.assigned_ambulance = nearest_ambulance.ambulance_id
            patient.status = 'Ambulance Assigned'
            
            nearest_ambulance.status = 'On Transfer'
            nearest_ambulance.current_patient = patient_id
            nearest_ambulance.destination = patient.receiving_hospital
            
            # Send automatic notifications
            self.notification_service.send_automated_notification('driver_assignment', {
                'patient': patient,
                'ambulance': nearest_ambulance
            })
            
            session.commit()
            st.success(f"🚑 Nearest ambulance {nearest_ambulance.ambulance_id} assigned to patient {patient.name}")
            return True
    
    def mark_patient_picked_up(self, patient_id: str) -> bool:
        """Mark patient as picked up and send notification"""
        with self.db_service.get_session() as session:
            patient = session.query(Patient).filter(Patient.patient_id == patient_id).first()
            if not patient:
                st.error("Patient not found")
                return False
            
            ambulance = session.query(Ambulance).filter(
                Ambulance.ambulance_id == patient.assigned_ambulance
            ).first()
            
            if not ambulance:
                st.error("Assigned ambulance not found")
                return False
            
            patient.status = 'Patient Picked Up'
            patient.pickup_notification_sent = True
            
            # Send automatic enroute notification to receiving hospital
            self.notification_service.send_automated_notification('patient_picked_up', {
                'patient': patient,
                'ambulance': ambulance
            })
            
            session.commit()
            st.success(f"✅ Patient {patient.name} marked as picked up. Receiving hospital notified.")
            return True
    
    def complete_mission(self, ambulance_id: str, patient_id: str) -> bool:
        """Complete mission with cost tracking and automatic notifications"""
        with self.db_service.get_session() as session:
            ambulance = session.query(Ambulance).filter(Ambulance.ambulance_id == ambulance_id).first()
            patient = session.query(Patient).filter(Patient.patient_id == patient_id).first()
            
            if not ambulance or not patient:
                st.error("Ambulance or patient not found")
                return False
            
            ambulance.status = 'Available'
            ambulance.current_patient = None
            ambulance.mission_complete = True
            patient.status = 'Arrived at Destination'
            
            # Calculate and update costs
            if patient.trip_distance:
                trip_cost = self.cost_service.update_ambulance_costs(
                    ambulance.ambulance_id, 
                    patient.trip_distance
                )
                
                if trip_cost:
                    patient.trip_fuel_cost = trip_cost['total_cost_ksh']
                    patient.trip_cost_savings = trip_cost['total_cost_ksh'] * 0.15
                    patient.actual_distance_covered = patient.trip_distance
            
            session.commit()
            
            # Send automatic arrival notification
            self.notification_service.send_automated_notification('arrival_notification', {
                'patient': patient,
                'ambulance': ambulance
            })
            
            st.success("Mission completed! Patient delivered successfully.")
            st.balloons()
            return True

# Enhanced Analytics Service with Cost Tracking
class AnalyticsService:
    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
        self.cost_service = CostCalculationService(db_service)
    
    def get_kpis(self) -> Dict[str, any]:
        with self.db_service.get_session() as session:
            total_patients = session.query(Patient).count()
            active_patients = session.query(Patient).filter(
                Patient.status.notin_(['Completed', 'Arrived at Destination'])
            ).count()
            total_ambulances = session.query(Ambulance).count()
            available_ambulances = session.query(Ambulance).filter(
                Ambulance.status == 'Available'
            ).count()
            
            # Calculate costs from completed handovers
            completed_handovers = session.query(HandoverForm).all()
            
            total_fuel_cost = sum(h.fuel_cost or 0 for h in completed_handovers)
            total_savings = sum(h.total_cost or 0 for h in completed_handovers) * 0.15  # 15% savings
            total_distance = sum(h.distance_covered or 0 for h in completed_handovers)
            
            completed_referrals = session.query(Patient).filter(
                Patient.status == 'Completed'
            ).count()
            
            avg_response_time = 0.0
            completion_rate = 0.0
            
            # Calculate fuel efficiency
            fuel_efficiency = 0
            if total_distance > 0:
                total_fuel_used = total_fuel_cost / Config.costs.fuel_price_per_liter
                fuel_efficiency = (total_distance / total_fuel_used) if total_fuel_used > 0 else 0
            
            return {
                'total_referrals': total_patients,
                'active_referrals': active_patients,
                'total_ambulances': total_ambulances,
                'available_ambulances': available_ambulances,
                'avg_response_time': f"{avg_response_time:.1f} min",
                'completion_rate': f"{completion_rate:.1f}%",
                'total_fuel_cost': total_fuel_cost,
                'total_cost_savings': total_savings,
                'total_distance_km': total_distance,
                'fuel_efficiency': f"{fuel_efficiency:.1f} km/L",
                'cost_efficiency': f"{(total_savings / total_fuel_cost * 100) if total_fuel_cost > 0 else 0:.1f}%"
            }
    
    def get_cost_analytics(self) -> Dict[str, any]:
        with self.db_service.get_session() as session:
            ambulances = session.query(Ambulance).all()
            handovers = session.query(HandoverForm).all()
            
            total_trip_costs = sum(h.total_cost or 0 for h in handovers)
            total_trip_savings = total_trip_costs * 0.15  # 15% savings
            
            # Generate monthly data based on actual handovers
            months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
            monthly_costs = [0] * 6
            monthly_savings = [0] * 6
            
            # Distribute costs across months based on actual data
            if handovers:
                avg_monthly_cost = total_trip_costs / 6
                monthly_costs = [avg_monthly_cost * (0.8 + i * 0.1) for i in range(6)]
                monthly_savings = [cost * 0.15 for cost in monthly_costs]
            
            return {
                'monthly_costs': monthly_costs,
                'monthly_savings': monthly_savings,
                'months': months,
                'total_trip_costs': total_trip_costs,
                'total_trip_savings': total_trip_savings,
                'ambulance_count': len(ambulances)
            }
    
    def get_referral_trends(self):
        with self.db_service.get_session() as session:
            patients = session.query(Patient).all()
            if patients:
                df = pd.DataFrame([{
                    'date': p.referral_time.date(),
                    'condition': p.condition,
                    'hospital': p.referring_hospital
                } for p in patients])
                trends = df.groupby('date').size().reset_index(name='count')
                return trends
            return pd.DataFrame()
    
    def get_hospital_stats(self):
        with self.db_service.get_session() as session:
            patients = session.query(Patient).all()
            if patients:
                df = pd.DataFrame([{
                    'hospital': p.referring_hospital,
                    'status': p.status
                } for p in patients])
                stats = df.groupby(['hospital', 'status']).size().reset_index(name='count')
                return stats
            return pd.DataFrame()

# Enhanced Ambulance Service
class AmbulanceService:
    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
    
    def get_available_ambulances_df(self):
        with self.db_service.get_session() as session:
            ambulances = session.query(Ambulance).filter(Ambulance.status == 'Available').all()
            data = []
            for ambulance in ambulances:
                data.append({
                    'Ambulance ID': ambulance.ambulance_id,
                    'Driver': ambulance.driver_name,
                    'Contact': ambulance.driver_contact,
                    'Location': ambulance.current_location,
                    'Status': ambulance.status,
                    'Fuel Level': f"{ambulance.fuel_level:.1f}%",
                    'Cost Efficiency': f"{(ambulance.cost_savings / ambulance.total_fuel_cost * 100) if ambulance.total_fuel_cost > 0 else 0:.1f}%"
                })
            return pd.DataFrame(data)
    
    def update_ambulance_location(self, ambulance_id: str, latitude: float, longitude: float, 
                                location_name: str, patient_id: Optional[str] = None) -> bool:
        try:
            with self.db_service.get_session() as session:
                ambulance = session.query(Ambulance).filter(
                    Ambulance.ambulance_id == ambulance_id
                ).first()
                if ambulance:
                    ambulance.latitude = latitude
                    ambulance.longitude = longitude
                    ambulance.current_location = location_name
                    ambulance.last_location_update = datetime.utcnow()
                    session.commit()
                    
                    location_data = {
                        'ambulance_id': ambulance_id,
                        'latitude': latitude,
                        'longitude': longitude,
                        'location_name': location_name,
                        'patient_id': patient_id
                    }
                    # Add location update record
                    location_update = LocationUpdate(**location_data)
                    session.add(location_update)
                    session.commit()
                    return True
        except Exception as e:
            logger.error(f"Error updating ambulance location: {str(e)}")
        return False
    
    def get_ambulance_with_fuel_info(self, ambulance_id: str):
        with self.db_service.get_session() as session:
            ambulance = session.query(Ambulance).filter(
                Ambulance.ambulance_id == ambulance_id
            ).first()
            
            if ambulance:
                fuel_status = "🟢 Good" if ambulance.fuel_level > 50 else "🟡 Low" if ambulance.fuel_level > 20 else "🔴 Critical"
                return {
                    'ambulance': ambulance,
                    'fuel_level': ambulance.fuel_level,
                    'fuel_status': fuel_status
                }
            return None
    
    def update_ambulance_fuel(self, ambulance_id: str, distance_km: Optional[float] = None, 
                             new_fuel_level: Optional[float] = None) -> Optional[float]:
        with self.db_service.get_session() as session:
            ambulance = session.query(Ambulance).filter(Ambulance.ambulance_id == ambulance_id).first()
            if ambulance:
                if distance_km is not None:
                    fuel_used = distance_km * ambulance.fuel_consumption_rate
                    fuel_used_percentage = (fuel_used / Config.costs.fuel_tank_capacity) * 100
                    ambulance.fuel_level = max(0, ambulance.fuel_level - fuel_used_percentage)
                elif new_fuel_level is not None:
                    ambulance.fuel_level = max(0, min(100, new_fuel_level))
                
                session.commit()
                return ambulance.fuel_level
            return None

# Location Simulator for Demo with Real Coordinates
class LocationSimulator:
    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
        self.running = False
    
    def start_simulation(self, ambulance_id: str, patient_id: str, start_lat: float, start_lng: float, 
                        end_lat: float, end_lng: float):
        """Simulate ambulance movement for demo purposes using real coordinates"""
        self.running = True
        ambulance_service = AmbulanceService(self.db_service)
        
        initial_distance = self.db_service.calculate_distance(start_lat, start_lng, end_lat, end_lng)
        
        current_lat, current_lng = start_lat, start_lng
        steps = 20
        lat_step = (end_lat - start_lat) / steps
        lng_step = (end_lng - start_lng) / steps
        
        for step in range(steps + 1):
            if not self.running:
                break
                
            current_lat = start_lat + (lat_step * step)
            current_lng = start_lng + (lng_step * step)
            
            ambulance_service.update_ambulance_location(
                ambulance_id, current_lat, current_lng, 
                f"En route - Step {step}/{steps}", patient_id
            )
            
            # Update fuel consumption
            if step > 0:
                distance_step = initial_distance / steps
                ambulance_service.update_ambulance_fuel(ambulance_id, distance_step)
            
            time.sleep(5)
        
        if self.running:
            # Mission completion
            referral_service = ReferralService(self.db_service, NotificationService(self.db_service))
            referral_service.complete_mission(ambulance_id, patient_id)
    
    def stop_simulation(self):
        self.running = False

# Enhanced UI Components
class DashboardUI:
    def __init__(self, analytics_service: AnalyticsService, db_service: DatabaseService):
        self.analytics = analytics_service
        self.db_service = db_service
    
    def display(self):
        st.title("📊 Dashboard Overview")
        
        kpis = self.analytics.get_kpis()
        
        self._display_kpi_metrics(kpis)
        
        col1, col2 = st.columns(2)
        with col1:
            self._display_cost_analytics()
        with col2:
            self._display_referral_trends()
        
        st.subheader("Recent Activity")
        self._display_recent_activity()

    def _display_kpi_metrics(self, kpis: Dict):
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("Total Referrals", kpis['total_referrals'])
        with col2:
            st.metric("Active Referrals", kpis['active_referrals'])
        with col3:
            st.metric("Available Ambulances", kpis['available_ambulances'])
        with col4:
            st.metric("Avg Response Time", kpis['avg_response_time'])
        with col5:
            st.metric("Completion Rate", kpis['completion_rate'])
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Fuel Cost", f"KSh {kpis['total_fuel_cost']:,.0f}")
        with col2:
            st.metric("Cost Savings", f"KSh {kpis['total_cost_savings']:,.0f}")
        with col3:
            st.metric("Total Distance", f"{kpis['total_distance_km']:,.1f} km")
        with col4:
            st.metric("Fuel Efficiency", kpis['fuel_efficiency'])

    def _display_cost_analytics(self):
        st.subheader("💰 Cost Analytics")
        cost_data = self.analytics.get_cost_analytics()
        
        # Only show chart if there are actual costs
        if cost_data['total_trip_costs'] > 0:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=cost_data['months'],
                y=cost_data['monthly_costs'],
                name='Costs Incurred',
                line=dict(color='red', width=2)
            ))
            fig.add_trace(go.Scatter(
                x=cost_data['months'],
                y=cost_data['monthly_savings'],
                name='Costs Saved',
                line=dict(color='green', width=2)
            ))
            fig.update_layout(
                title='Monthly Costs vs Savings',
                xaxis_title='Month',
                yaxis_title='Amount (KSh)',
                hovermode='x unified'
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # Additional cost metrics
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Trip Costs", f"KSh {cost_data['total_trip_costs']:,.0f}")
            with col2:
                st.metric("Total Trip Savings", f"KSh {cost_data['total_trip_savings']:,.0f}")
        else:
            st.info("No cost data available yet. Costs will appear after patient handovers are completed.")

    def _display_referral_trends(self):
        st.subheader("📈 Referral Trends")
        
        trends_data = self.analytics.get_referral_trends()
        if not trends_data.empty:
            fig = px.line(trends_data, x='date', y='count', title="Daily Referrals")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No referral data available yet")

    def _display_recent_activity(self):
        with self.db_service.get_session() as session:
            recent_patients = session.query(Patient).order_by(
                Patient.referral_time.desc()
            ).limit(5).all()
            
            if recent_patients:
                data = []
                for patient in recent_patients:
                    cost_info = ""
                    if patient.trip_fuel_cost:
                        cost_info = f"KSh {patient.trip_fuel_cost:,.0f}"
                        if patient.trip_cost_savings:
                            cost_info += f" (Saved: KSh {patient.trip_cost_savings:,.0f})"
                    
                    data.append({
                        'Patient ID': patient.patient_id[:8] + '...',
                        'Name': patient.name,
                        'Gender': patient.gender,
                        'Condition': patient.condition,
                        'From': patient.referring_hospital,
                        'To': patient.receiving_hospital,
                        'Status': patient.status,
                        'Distance': f"{patient.trip_distance or 0:.1f} km",
                        'Cost': cost_info,
                        'Time': patient.referral_time.strftime('%Y-%m-%d %H:%M')
                    })
                
                st.dataframe(pd.DataFrame(data), use_container_width=True)
            else:
                st.info("No recent activity")

# Enhanced ReferralUI with automatic notifications and cost tracking
class ReferralUI:
    def __init__(self, referral_service: ReferralService, db_service: DatabaseService):
        self.referral_service = referral_service
        self.db_service = db_service
    
    def display(self):
        st.title("📋 Patient Referral Management")
        
        tab1, tab2, tab3 = st.tabs(["Create Referral", "Active Referrals", "Referral History"])
        
        with tab1:
            self._create_referral_form()
        with tab2:
            self._display_active_referrals()
        with tab3:
            self._display_referral_history()

    def _create_referral_form(self):
        st.subheader("Create New Patient Referral")
        
        with st.form("referral_form", clear_on_submit=True):
            patient_data = self._get_patient_form_data()
            
            submitted = st.form_submit_button("Create Referral", use_container_width=True)
            if submitted:
                is_valid, error_message = self._validate_patient_data(patient_data)
                
                if not is_valid:
                    st.error(error_message)
                else:
                    user = st.session_state.user
                    patient = self.referral_service.create_referral(patient_data, user)
                    
                    if patient:
                        st.success(f"Referral created successfully! Patient ID: {patient.patient_id}")

    def _get_patient_form_data(self) -> Dict:
        col1, col2 = st.columns(2)
        
        with col1:
            name = st.text_input("Patient Name*")
            age = st.number_input("Age*", min_value=0, max_value=120, value=30)
            gender = st.selectbox("Gender*", ["Male", "Female", "Other"])
            condition = st.text_input("Medical Condition*")
            referring_physician = st.text_input("Referring Physician*")
            referring_hospital = st.selectbox("Referring Hospital*", self._get_hospital_options())
        
        with col2:
            receiving_hospital = st.selectbox("Receiving Hospital*", self._get_receiving_hospitals())
            receiving_physician = st.text_input("Receiving Physician")
            notes = st.text_area("Clinical Notes")
        
        with st.expander("Additional Medical Information"):
            medical_history = st.text_area("Medical History")
            current_medications = st.text_area("Current Medications")
            allergies = st.text_area("Allergies")
        
        # Calculate and display distance and cost estimate
        if referring_hospital and receiving_hospital:
            distance = self._calculate_distance_between_hospitals(referring_hospital, receiving_hospital)
            if distance:
                cost_service = CostCalculationService(self.db_service)
                cost_estimate = cost_service.calculate_trip_cost(distance)
                
                st.subheader("📊 Trip Details")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Estimated Distance", f"{distance} km")
                with col2:
                    st.metric("Estimated Fuel Cost", f"KSh {cost_estimate['fuel_cost_ksh']:,.0f}")
                with col3:
                    st.metric("Total Estimated Cost", f"KSh {cost_estimate['total_cost_ksh']:,.0f}")
        
        st.subheader("🚑 Ambulance Assignment")
        ambulance_assignment_type = st.radio(
            "Ambulance Assignment",
            ["Auto-assign nearest ambulance", "Select specific ambulance"],
            horizontal=True
        )
        
        assigned_ambulance = None
        auto_assign_ambulance = False
        
        if ambulance_assignment_type == "Auto-assign nearest ambulance":
            auto_assign_ambulance = True
            st.info("The system will automatically assign the nearest available ambulance with sufficient fuel.")
        else:
            with self.db_service.get_session() as session:
                available_ambulances = session.query(Ambulance).filter(Ambulance.status == 'Available').all()
                if available_ambulances:
                    ambulance_options = {f"{amb.ambulance_id} - {amb.driver_name} (Fuel: {amb.fuel_level:.1f}%)": amb.ambulance_id for amb in available_ambulances}
                    ambulance_choice = st.selectbox("Select Ambulance", list(ambulance_options.keys()))
                    if ambulance_choice:
                        assigned_ambulance = ambulance_options[ambulance_choice]
                else:
                    st.warning("No available ambulances. Please try auto-assignment or wait for an ambulance to become available.")
        
        return {
            'name': name, 'age': age, 'gender': gender, 'condition': condition,
            'referring_physician': referring_physician, 'referring_hospital': referring_hospital,
            'receiving_hospital': receiving_hospital, 'receiving_physician': receiving_physician,
            'notes': notes, 'medical_history': medical_history,
            'current_medications': current_medications, 'allergies': allergies,
            'auto_assign_ambulance': auto_assign_ambulance,
            'assigned_ambulance': assigned_ambulance
        }

    def _calculate_distance_between_hospitals(self, referring_hospital: str, receiving_hospital: str) -> Optional[float]:
        if referring_hospital in HOSPITAL_LOCATIONS and receiving_hospital in HOSPITAL_LOCATIONS:
            ref_loc = HOSPITAL_LOCATIONS[referring_hospital]
            rec_loc = HOSPITAL_LOCATIONS[receiving_hospital]
            
            distance = self.db_service.calculate_distance(
                ref_loc['lat'], ref_loc['lng'],
                rec_loc['lat'], rec_loc['lng']
            )
            return distance
        return None

    def _validate_patient_data(self, data: Dict) -> Tuple[bool, Optional[str]]:
        required_fields = {
            'name': 'Patient name',
            'age': 'Patient age',
            'gender': 'Patient gender',
            'condition': 'Medical condition',
            'referring_hospital': 'Referring hospital',
            'receiving_hospital': 'Receiving hospital',
            'referring_physician': 'Referring physician'
        }
        
        for field, description in required_fields.items():
            if not data.get(field):
                return False, f"{description} is required"
        
        if data.get('age') and (data['age'] < 0 or data['age'] > 150):
            return False, "Age must be between 0 and 150"
        
        if data.get('referring_hospital') == data.get('receiving_hospital'):
            return False, "Referring and receiving hospitals cannot be the same"
        
        return True, None

    def _get_hospital_options(self) -> List[str]:
        user_hospital = st.session_state.user['hospital']
        
        if user_hospital == "All Facilities":
            return self._get_all_hospitals()
        else:
            return [user_hospital]

    def _get_receiving_hospitals(self) -> List[str]:
        user_hospital = st.session_state.user['hospital']
        
        if user_hospital in ["All Facilities", "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", 
                           "Kisumu County Referral Hospital (KCRH)"]:
            return ["Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", 
                   "Kisumu County Referral Hospital (KCRH)"]
        else:
            return ["Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", 
                   "Kisumu County Referral Hospital (KCRH)"]

    def _get_all_hospitals(self) -> List[str]:
        return list(HOSPITAL_LOCATIONS.keys())

    def _display_active_referrals(self):
        st.subheader("Active Referrals")
        
        with self.db_service.get_session() as session:
            user_hospital = st.session_state.user['hospital']
            active_patients = self._get_filtered_patients(session, user_hospital, active_only=True)
            
            if active_patients:
                self._display_patients_table(active_patients)
                
                # Show patient actions for staff and admin
                if st.session_state.user['role'] in ['Admin', 'Hospital Staff']:
                    st.subheader("Patient Actions")
                    for patient in active_patients:
                        with st.expander(f"Actions for {patient.name} ({patient.patient_id})"):
                            self._display_patient_actions(patient)
            else:
                st.info("No active referrals")

    def _display_patient_actions(self, patient):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button(f"Assign Ambulance", key=f"assign_{patient.patient_id}", use_container_width=True):
                st.session_state[f'assign_ambulance_{patient.patient_id}'] = True
            
            if st.session_state.get(f'assign_ambulance_{patient.patient_id}'):
                with self.db_service.get_session() as session:
                    available_ambulances = session.query(Ambulance).filter(Ambulance.status == 'Available').all()
                    if available_ambulances:
                        ambulance_options = [
                            f"{amb.ambulance_id} - {amb.driver_name} (Fuel: {amb.fuel_level:.1f}%)" 
                            for amb in available_ambulances
                        ]
                        selected_ambulance = st.selectbox("Select Ambulance", ambulance_options, key=f"amb_select_{patient.patient_id}")
                        if st.button("Confirm Assignment", key=f"confirm_{patient.patient_id}", use_container_width=True):
                            ambulance_id = selected_ambulance.split(" - ")[0]
                            if self.referral_service.assign_ambulance(patient.patient_id, ambulance_id):
                                st.success("Ambulance assigned successfully!")
                                st.session_state[f'assign_ambulance_{patient.patient_id}'] = False
                                st.rerun()
                    else:
                        st.warning("No available ambulances")
        
        with col2:
            if st.button("Update Status", key=f"status_{patient.patient_id}", use_container_width=True):
                st.session_state[f'update_status_{patient.patient_id}'] = True
            
            if st.session_state.get(f'update_status_{patient.patient_id}'):
                new_status = st.selectbox("New Status", 
                    ["Referred", "Ambulance Dispatched", "Patient Picked Up", 
                     "Transporting to Destination", "Arrived at Destination"],
                    key=f"status_select_{patient.patient_id}")
                if st.button("Update", key=f"update_{patient.patient_id}", use_container_width=True):
                    with self.db_service.get_session() as session:
                        patient_obj = session.query(Patient).filter(Patient.patient_id == patient.patient_id).first()
                        if patient_obj:
                            patient_obj.status = new_status
                            session.commit()
                            st.success("Status updated!")
                            st.session_state[f'update_status_{patient.patient_id}'] = False
                            st.rerun()
        
        with col3:
            if (st.session_state.user['role'] == 'Ambulance Driver' and 
                patient.assigned_ambulance and 
                patient.status == 'Ambulance Dispatched'):
                if st.button("Mark Patient Picked Up", key=f"pickup_{patient.patient_id}", use_container_width=True):
                    if self.referral_service.mark_patient_picked_up(patient.patient_id):
                        st.rerun()

    def _display_referral_history(self):
        st.subheader("Referral History")
        
        with self.db_service.get_session() as session:
            user_hospital = st.session_state.user['hospital']
            all_patients = self._get_filtered_patients(session, user_hospital, active_only=False)
            
            if all_patients:
                self._display_patients_table(all_patients)
            else:
                st.info("No referral history")

    def _get_filtered_patients(self, session, user_hospital: str, active_only: bool = True):
        query = session.query(Patient)
        
        if user_hospital != "All Facilities":
            if user_hospital in ["Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", 
                               "Kisumu County Referral Hospital (KCRH)"]:
                query = query.filter(Patient.receiving_hospital == user_hospital)
            else:
                query = query.filter(Patient.referring_hospital == user_hospital)
        
        if active_only:
            query = query.filter(Patient.status.notin_(['Completed', 'Arrived at Destination']))
        
        return query.order_by(Patient.referral_time.desc()).all()

    def _display_patients_table(self, patients: List[Patient]):
        data = []
        for patient in patients:
            ambulance_info = patient.assigned_ambulance or "Not assigned"
            cost_info = ""
            if patient.trip_fuel_cost:
                cost_info = f"KSh {patient.trip_fuel_cost:,.0f}"
                if patient.trip_cost_savings:
                    cost_info += f" (Saved: KSh {patient.trip_cost_savings:,.0f})"
            
            data.append({
                'Patient ID': patient.patient_id[:8] + '...',
                'Name': patient.name,
                'Gender': patient.gender,
                'Condition': patient.condition,
                'From': patient.referring_hospital,
                'To': patient.receiving_hospital,
                'Status': patient.status,
                'Ambulance': ambulance_info,
                'Distance': f"{patient.trip_distance or 0:.1f} km",
                'Cost': cost_info,
                'Time': patient.referral_time.strftime('%Y-%m-%d %H:%M')
            })
        
        st.dataframe(pd.DataFrame(data), use_container_width=True)

# Enhanced Cost Management UI
class CostManagementUI:
    def __init__(self, analytics_service: AnalyticsService, db_service: DatabaseService):
        self.analytics = analytics_service
        self.db_service = db_service
        self.cost_service = CostCalculationService(db_service)
    
    def display(self):
        st.title("💰 Cost Management & Analytics")
        
        tab1, tab2, tab3, tab4 = st.tabs(["Cost Overview", "Fuel Management", "Savings Analysis", "Budget Planning"])
        
        with tab1:
            self._display_cost_overview()
        with tab2:
            self._display_fuel_management()
        with tab3:
            self._display_savings_analysis()
        with tab4:
            self._display_budget_planning()

    def _display_cost_overview(self):
        st.subheader("📈 Cost Overview")
        
        kpis = self.analytics.get_kpis()
        cost_data = self.analytics.get_cost_analytics()
        
        # Only show metrics if there are actual costs
        if cost_data['total_trip_costs'] > 0:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Fuel Cost", f"KSh {kpis['total_fuel_cost']:,.0f}")
            with col2:
                st.metric("Total Savings", f"KSh {kpis['total_cost_savings']:,.0f}")
            with col3:
                st.metric("Net Cost", f"KSh {kpis['total_fuel_cost'] - kpis['total_cost_savings']:,.0f}")
            with col4:
                savings_rate = (kpis['total_cost_savings'] / kpis['total_fuel_cost'] * 100) if kpis['total_fuel_cost'] > 0 else 0
                st.metric("Savings Rate", f"{savings_rate:.1f}%")
            
            st.subheader("Cost Distribution")
            with self.db_service.get_session() as session:
                ambulances = session.query(Ambulance).all()
                handovers = session.query(HandoverForm).all()
                
                if ambulances and handovers:
                    cost_distribution = []
                    for ambulance in ambulances:
                        # Calculate ambulance-specific costs from handovers
                        ambulance_handovers = [h for h in handovers if h.ambulance_id == ambulance.ambulance_id]
                        ambulance_fuel_cost = sum(h.fuel_cost or 0 for h in ambulance_handovers)
                        ambulance_savings = sum(h.total_cost or 0 for h in ambulance_handovers) * 0.15
                        
                        if ambulance_fuel_cost > 0:  # Only show ambulances with costs
                            cost_distribution.append({
                                'Ambulance': ambulance.ambulance_id,
                                'Fuel Cost': ambulance_fuel_cost,
                                'Savings': ambulance_savings
                            })
                    
                    if cost_distribution:
                        df = pd.DataFrame(cost_distribution)
                        fig = px.bar(df, x='Ambulance', y=['Fuel Cost', 'Savings'],
                                    title="Cost Distribution by Ambulance",
                                    barmode='group')
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No cost distribution data available yet")
        else:
            st.info("No cost data available yet. Costs will appear after patient handovers are completed.")

    def _display_fuel_management(self):
        st.subheader("⛽ Fuel Management")
        
        with self.db_service.get_session() as session:
            ambulances = session.query(Ambulance).all()
            handovers = session.query(HandoverForm).all()
        
        st.subheader("Fuel Price Settings")
        col1, col2 = st.columns(2)
        with col1:
            current_price = st.number_input(
                "Current Fuel Price (KSh/L)",
                value=float(Config.costs.fuel_price_per_liter),
                min_value=100.0,
                max_value=300.0,
                step=1.0
            )
        
        with col2:
            if st.button("Update Fuel Price", use_container_width=True):
                Config.costs.fuel_price_per_liter = current_price
                st.success("Fuel price updated successfully!")
        
        st.subheader("Fuel Efficiency Analysis")
        efficiency_data = []
        for ambulance in ambulances:
            # Calculate efficiency from handovers
            ambulance_handovers = [h for h in handovers if h.ambulance_id == ambulance.ambulance_id]
            total_distance = sum(h.distance_covered or 0 for h in ambulance_handovers)
            total_fuel_cost = sum(h.fuel_cost or 0 for h in ambulance_handovers)
            
            if total_distance > 0 and total_fuel_cost > 0:
                fuel_used_liters = total_fuel_cost / Config.costs.fuel_price_per_liter
                efficiency = total_distance / fuel_used_liters if fuel_used_liters > 0 else 0
                
                efficiency_data.append({
                    'Ambulance': ambulance.ambulance_id,
                    'Distance (km)': total_distance,
                    'Fuel Used (L)': fuel_used_liters,
                    'Efficiency (km/L)': efficiency,
                    'Cost per km': total_fuel_cost / total_distance
                })
        
        if efficiency_data:
            df = pd.DataFrame(efficiency_data)
            st.dataframe(df, use_container_width=True)
            
            fig = px.bar(df, x='Ambulance', y='Efficiency (km/L)',
                        title="Fuel Efficiency by Ambulance")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No fuel efficiency data available yet. Complete handovers to see efficiency data.")
        
        st.subheader("Ambulance Fuel Status")
        for ambulance in ambulances:
            fuel_status = "🟢 Good" if ambulance.fuel_level > 50 else "🟡 Low" if ambulance.fuel_level > 20 else "🔴 Critical"
            
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.write(f"**{ambulance.ambulance_id}** - {ambulance.driver_name}")
            with col2:
                st.write(f"{fuel_status} ({ambulance.fuel_level:.1f}%)")
            with col3:
                if st.button("Refuel", key=f"refuel_{ambulance.ambulance_id}"):
                    with self.db_service.get_session() as session:
                        ambulance_obj = session.query(Ambulance).filter(Ambulance.ambulance_id == ambulance.ambulance_id).first()
                        if ambulance_obj:
                            ambulance_obj.fuel_level = 100.0
                            session.commit()
                            st.success(f"{ambulance.ambulance_id} refueled to 100%")
                            st.rerun()

    def _display_savings_analysis(self):
        st.subheader("💵 Savings Analysis")
        
        cost_data = self.analytics.get_cost_analytics()
        
        if cost_data['total_trip_savings'] > 0:
            fig = px.area(
                x=cost_data['months'],
                y=cost_data['monthly_savings'],
                title="Monthly Cost Savings Trend",
                labels={'x': 'Month', 'y': 'Savings (KSh)'}
            )
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Savings Breakdown")
            with self.db_service.get_session() as session:
                ambulances = session.query(Ambulance).all()
                handovers = session.query(HandoverForm).all()
                
                savings_data = []
                for ambulance in ambulances:
                    ambulance_handovers = [h for h in handovers if h.ambulance_id == ambulance.ambulance_id]
                    ambulance_savings = sum(h.total_cost or 0 for h in ambulance_handovers) * 0.15
                    ambulance_fuel_cost = sum(h.fuel_cost or 0 for h in ambulance_handovers)
                    
                    if ambulance_savings > 0:  # Only show ambulances with savings
                        savings_data.append({
                            'Ambulance': ambulance.ambulance_id,
                            'Savings': ambulance_savings,
                            'Savings Rate': (ambulance_savings / ambulance_fuel_cost * 100) if ambulance_fuel_cost > 0 else 0
                        })
                
                if savings_data:
                    df = pd.DataFrame(savings_data)
                    col1, col2 = st.columns(2)
                    with col1:
                        st.dataframe(df, use_container_width=True)
                    with col2:
                        fig = px.pie(df, values='Savings', names='Ambulance',
                                    title="Savings Distribution by Ambulance")
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No savings data available yet")
        else:
            st.info("No savings data available yet. Savings will appear after patient handovers are completed.")

    def _display_budget_planning(self):
        st.subheader("📊 Budget Planning & Forecasting")
        
        col1, col2 = st.columns(2)
        with col1:
            monthly_budget = st.number_input("Monthly Budget (KSh)", 
                                           value=500000, 
                                           min_value=100000, 
                                           max_value=5000000)
        with col2:
            expected_trips = st.number_input("Expected Monthly Trips", 
                                           value=100, 
                                           min_value=10, 
                                           max_value=1000)
        
        avg_trip_cost = 1500
        projected_cost = expected_trips * avg_trip_cost
        projected_savings = projected_cost * 0.15
        net_projected_cost = projected_cost - projected_savings
        
        st.subheader("Budget Projections")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Projected Cost", f"KSh {projected_cost:,.0f}")
        with col2:
            st.metric("Projected Savings", f"KSh {projected_savings:,.0f}")
        with col3:
            status = "Within Budget" if net_projected_cost <= monthly_budget else "Over Budget"
            st.metric("Budget Status", status, 
                     delta=f"KSh {monthly_budget - net_projected_cost:,.0f}")
        
        budget_data = {
            'Category': ['Projected Cost', 'Projected Savings', 'Net Cost'],
            'Amount': [projected_cost, projected_savings, net_projected_cost]
        }
        df = pd.DataFrame(budget_data)
        fig = px.bar(df, x='Category', y='Amount', 
                    title="Budget Utilization Projection")
        st.plotly_chart(fig, use_container_width=True)

# Enhanced Tracking UI with Real Coordinates and Cost Analysis
class TrackingUI:
    def __init__(self, db_service: DatabaseService, cost_service: CostCalculationService):
        self.db_service = db_service
        self.cost_service = cost_service
    
    def display(self):
        st.title("🚑 Ambulance Tracking & Cost Management")
        
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("🔄 Refresh Data", use_container_width=True):
                st.rerun()
        
        st.markdown("### 🗺️ Real-time Ambulance Tracking with Cost Analysis")
        
        # Display map with all ambulances and hospitals
        self._display_comprehensive_map()
        
        with self.db_service.get_session() as session:
            patients = session.query(Patient).all()
            active_transfers = [p for p in patients if p.status in ['Ambulance Dispatched', 'Patient Picked Up', 'Transporting to Destination']]
            
            if active_transfers:
                for patient in active_transfers:
                    with st.expander(f"🚑 {patient.name} - {patient.condition}", expanded=True):
                        ambulance = None
                        if patient.assigned_ambulance:
                            ambulance = session.query(Ambulance).filter(
                                Ambulance.ambulance_id == patient.assigned_ambulance
                            ).first()
                        
                        if ambulance and patient.trip_distance:
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                estimated_cost = self.cost_service.calculate_trip_cost(patient.trip_distance)
                                st.metric("Estimated Cost", f"KSh {estimated_cost['total_cost_ksh']:,.0f}")
                            with col2:
                                st.metric("Distance", f"{patient.trip_distance:.1f} km")
                            with col3:
                                fuel_used = patient.trip_distance * ambulance.fuel_consumption_rate
                                st.metric("Fuel Needed", f"{fuel_used:.1f} L")
                            with col4:
                                potential_savings = estimated_cost['total_cost_ksh'] * 0.15
                                st.metric("Potential Savings", f"KSh {potential_savings:,.0f}")
                        
                        # Display map and tracking info
                        self._display_tracking_info(patient, ambulance)
            
            else:
                st.info("No active patient transfers to track")
            
            st.markdown("### 🚑 Ambulance Fleet Cost Analysis")
            self._display_ambulance_cost_list(session)

    def _display_comprehensive_map(self):
        """Display a comprehensive map showing all ambulances and hospitals with real coordinates"""
        map_data = []
        
        # Add hospitals to map
        for hospital_name, location in HOSPITAL_LOCATIONS.items():
            map_data.append({
                'lat': location['lat'],
                'lon': location['lng'],
                'name': hospital_name,
                'type': 'hospital',
                'color': [0, 0, 255],  # Blue for hospitals
                'size': 100
            })
        
        # Add ambulances to map
        with self.db_service.get_session() as session:
            ambulances = session.query(Ambulance).all()
            for ambulance in ambulances:
                if ambulance.latitude and ambulance.longitude:
                    # Red for ambulance in motion, green for available
                    color = [255, 0, 0] if ambulance.status == 'On Transfer' else [0, 255, 0]
                    map_data.append({
                        'lat': ambulance.latitude,
                        'lon': ambulance.longitude,
                        'name': f"{ambulance.ambulance_id} - {ambulance.driver_name}",
                        'type': 'ambulance',
                        'color': color,
                        'size': 50,
                        'status': ambulance.status
                    })
        
        if map_data:
            df = pd.DataFrame(map_data)
            
            # Create a pydeck map with better visualization
            layer = pdk.Layer(
                'ScatterplotLayer',
                data=df,
                get_position='[lon, lat]',
                get_color='color',
                get_radius='size',
                pickable=True,
                radius_min_pixels=10,
                radius_max_pixels=100,
            )
            
            view_state = pdk.ViewState(
                latitude=-0.0916,
                longitude=34.7680,
                zoom=10,
                pitch=0
            )
            
            r = pdk.Deck(
                layers=[layer],
                initial_view_state=view_state,
                tooltip={
                    'html': '<b>{name}</b><br>{type} - {status}',
                    'style': {
                        'color': 'white'
                    }
                }
            )
            
            st.pydeck_chart(r)
        else:
            st.info("No location data available for mapping")

    def _display_tracking_info(self, patient, ambulance):
        if ambulance:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Ambulance", ambulance.ambulance_id)
            with col2:
                st.metric("Driver", ambulance.driver_name)
            with col3:
                fuel_status = "🟢 Good" if ambulance.fuel_level > 50 else "🟡 Low" if ambulance.fuel_level > 20 else "🔴 Critical"
                st.metric("Fuel Level", f"{ambulance.fuel_level:.1f}%", fuel_status)
            with col4:
                st.metric("Status", ambulance.status)
            
            # Enhanced map display for individual patient with real coordinates
            st.subheader("📍 Current Location")
            if ambulance.latitude and ambulance.longitude:
                # Create map data with different colors for specific locations
                map_data = []
                
                # Add ambulance location (RED)
                map_data.append({
                    'lat': ambulance.latitude,
                    'lon': ambulance.longitude,
                    'name': f'Ambulance: {ambulance.ambulance_id}',
                    'color': 'red'
                })
                
                # Add referring hospital location (BLUE)
                if patient.referring_hospital_lat and patient.referring_hospital_lng:
                    map_data.append({
                        'lat': patient.referring_hospital_lat,
                        'lon': patient.referring_hospital_lng,
                        'name': f'Pickup: {patient.referring_hospital}',
                        'color': 'blue'
                    })
                
                # Add receiving hospital location (GREEN)
                if patient.receiving_hospital_lat and patient.receiving_hospital_lng:
                    map_data.append({
                        'lat': patient.receiving_hospital_lat,
                        'lon': patient.receiving_hospital_lng,
                        'name': f'Destination: {patient.receiving_hospital}',
                        'color': 'green'
                    })
                
                df_map = pd.DataFrame(map_data)
                
                # Use Pydeck for better visualization
                layer = pdk.Layer(
                    'ScatterplotLayer',
                    data=df_map,
                    get_position='[lon, lat]',
                    get_color='color',
                    get_radius=200,
                    pickable=True
                )
                
                view_state = pdk.ViewState(
                    latitude=ambulance.latitude,
                    longitude=ambulance.longitude,
                    zoom=12,
                    pitch=0
                )
                
                r = pdk.Deck(
                    layers=[layer],
                    initial_view_state=view_state,
                    tooltip={
                        'html': '<b>{name}</b>',
                        'style': {
                            'color': 'white'
                        }
                    }
                )
                
                st.pydeck_chart(r)
            else:
                st.info("Location data not available")

    def _display_ambulance_cost_list(self, session):
        ambulances = session.query(Ambulance).all()
        handovers = session.query(HandoverForm).all()
        
        for ambulance in ambulances:
            status_color = "🟢" if ambulance.status == 'Available' else "🔴"
            fuel_indicator = "🟢" if ambulance.fuel_level > 50 else "🟡" if ambulance.fuel_level > 20 else "🔴"
            
            # Calculate costs from handovers
            ambulance_handovers = [h for h in handovers if h.ambulance_id == ambulance.ambulance_id]
            total_fuel_cost = sum(h.fuel_cost or 0 for h in ambulance_handovers)
            total_savings = total_fuel_cost * 0.15
            total_distance = sum(h.distance_covered or 0 for h in ambulance_handovers)
            
            with st.expander(f"{status_color} {ambulance.ambulance_id} - {ambulance.driver_name} {fuel_indicator} Fuel: {ambulance.fuel_level:.1f}%", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Status:** {ambulance.status}")
                    st.write(f"**Location:** {ambulance.current_location}")
                    st.write(f"**Contact:** {ambulance.driver_contact}")
                    st.write(f"**Total Distance:** {total_distance:,.1f} km")
                
                with col2:
                    st.write(f"**Fuel Level:** {ambulance.fuel_level:.1f}%")
                    st.write(f"**Fuel Cost:** KSh {total_fuel_cost:,.0f}")
                    st.write(f"**Cost Savings:** KSh {total_savings:,.0f}")
                    st.write(f"**Efficiency:** {(total_savings / total_fuel_cost * 100) if total_fuel_cost > 0 else 0:.1f}%")
                
                if ambulance.current_patient:
                    patient = session.query(Patient).filter(Patient.patient_id == ambulance.current_patient).first()
                    if patient:
                        st.write(f"**Current Patient:** {patient.name}")
                        st.write(f"**Destination:** {patient.receiving_hospital}")
                        
                        if patient.trip_distance:
                            cost_info = self.cost_service.calculate_trip_cost(
                                patient.trip_distance, 
                                ambulance.fuel_consumption_rate
                            )
                            st.write(f"**Trip Cost Estimate:** KSh {cost_info['total_cost_ksh']:,.0f}")

# Enhanced Communication UI
class CommunicationUI:
    def __init__(self, db_service: DatabaseService, notification_service: NotificationService):
        self.db_service = db_service
        self.notification_service = notification_service
    
    def display(self):
        st.title("💬 Communication Center")
        
        tab1, tab2, tab3, tab4 = st.tabs(["All Messages", "Send Message", "Message Templates", "Notification Log"])
        
        with tab1:
            self._display_all_messages()
        with tab2:
            self._send_custom_message()
        with tab3:
            self._message_templates()
        with tab4:
            self._notification_log()

    def _display_all_messages(self):
        st.subheader("📨 All Messages & Notifications")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_type = st.selectbox("Filter by Type", 
                ["All Messages", "Automatic Notifications", "Manual Messages", "Driver Messages"])
        with col2:
            filter_status = st.selectbox("Filter by Status", 
                ["All Status", "Unread", "Read"])
        with col3:
            if st.button("🔄 Refresh Messages", use_container_width=True):
                st.rerun()
        
        with self.db_service.get_session() as session:
            all_communications = session.query(Communication).order_by(Communication.timestamp.desc()).all()
            
            if not all_communications:
                st.info("No messages found")
                return
            
            filtered_comms = all_communications
            if filter_type == "Automatic Notifications":
                filtered_comms = [c for c in all_communications if c.sender == 'System']
            elif filter_type == "Manual Messages":
                filtered_comms = [c for c in all_communications if c.sender != 'System' and c.sender != 'Driver']
            elif filter_type == "Driver Messages":
                filtered_comms = [c for c in all_communications if c.sender == 'Driver']
            
            for comm in filtered_comms:
                if comm.sender == 'System':
                    icon = "🤖"
                    bg_color = "#e8f4fd"
                    border_color = "#1e88e5"
                elif comm.sender == 'Driver':
                    icon = "🚑"
                    bg_color = "#e8f5e8"
                    border_color = "#4caf50"
                else:
                    icon = "👨‍⚕️"
                    bg_color = "#fff3e0"
                    border_color = "#ff9800"
                
                with st.container():
                    st.markdown(f"""
                    <div style="
                        background-color: {bg_color};
                        border: 2px solid {border_color};
                        border-radius: 10px;
                        padding: 15px;
                        margin: 10px 0;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    ">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong>{icon} {comm.sender}</strong> → <strong>{comm.receiver}</strong>
                            </div>
                            <div style="font-size: 0.8em; color: #666;">
                                {comm.timestamp.strftime('%Y-%m-%d %H:%M')}
                            </div>
                        </div>
                        <div style="margin: 10px 0; padding: 10px; background: white; border-radius: 5px;">
                            {comm.message}
                        </div>
                        <div style="font-size: 0.8em; color: #888;">
                            Patient: {comm.patient_id or 'N/A'} | 
                            Ambulance: {comm.ambulance_id or 'N/A'} | 
                            Type: {comm.message_type or 'General'}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

    def _send_custom_message(self):
        st.subheader("✉️ Send Custom Message")
        with st.form("custom_message_form"):
            with self.db_service.get_session() as session:
                patients = session.query(Patient).all()
                ambulances = session.query(Ambulance).all()
                
                col1, col2 = st.columns(2)
                with col1:
                    patient_options = ["Select Patient"] + [f"{p.patient_id} - {p.name}" for p in patients]
                    selected_patient = st.selectbox("Related Patient", patient_options)
                    
                    sender = st.selectbox("Sender", 
                        ["System", st.session_state.user.get('name', st.session_state.user['role'])])
                    
                with col2:
                    ambulance_options = ["Select Ambulance"] + [f"{a.ambulance_id} - {a.driver_name}" for a in ambulances]
                    selected_ambulance = st.selectbox("Related Ambulance", ambulance_options)
                    
                    receiver_options = ["Select Receiver"] + [a.driver_name for a in ambulances] + list(HOSPITAL_LOCATIONS.keys())
                    receiver = st.selectbox("Receiver", receiver_options)
                
                message_type = st.selectbox("Message Type", 
                    ["General", "Urgent", "Update", "Emergency", "Instruction"])
                
                message = st.text_area("Message", height=150, 
                    placeholder="Type your message here...")
                
                col1, col2 = st.columns(2)
                with col1:
                    priority = st.selectbox("Priority", ["Normal", "High", "Urgent"])
                with col2:
                    require_confirmation = st.checkbox("Require Confirmation", value=False)
                
                submitted = st.form_submit_button("Send Message", use_container_width=True)
                if submitted:
                    if not message or receiver == "Select Receiver":
                        st.error("Please fill in all required fields")
                    else:
                        patient_id = selected_patient.split(" - ")[0] if selected_patient != "Select Patient" else None
                        ambulance_id = selected_ambulance.split(" - ")[0] if selected_ambulance != "Select Ambulance" else None
                        
                        comm_data = {
                            'patient_id': patient_id,
                            'ambulance_id': ambulance_id,
                            'sender': sender,
                            'receiver': receiver,
                            'message': message,
                            'message_type': f"manual_{message_type.lower()}"
                        }
                        communication = Communication(**comm_data)
                        session.add(communication)
                        session.commit()
                        
                        st.success(f"✅ Message sent to {receiver}")
                        
                        if require_confirmation:
                            st.info("📬 Confirmation request sent with the message")

    def _message_templates(self):
        st.subheader("📋 Message Templates")
        
        template_categories = {
            "Emergency": {
                "Cardiac Emergency": "🚨 CARDIAC EMERGENCY: Patient with chest pain and suspected MI. Prepare cath lab and emergency team. ETA 15 minutes.",
                "Trauma Alert": "🚨 TRAUMA ALERT: Multiple trauma patient incoming. Activate trauma team. ETA 10 minutes.",
                "Stroke Alert": "🚨 STROKE ALERT: Patient with acute neurological symptoms. Prepare stroke team and CT scan. ETA 12 minutes."
            },
            "Status Updates": {
                "ETA Update": "📍 ETA UPDATE: Current ETA revised to {eta} minutes. Patient condition {condition}.",
                "Delay Notification": "⏱️ DELAY: Experiencing {reason}. Revised ETA {eta} minutes.",
                "Arrival Imminent": "🎯 ARRIVAL IMMINENT: Ambulance arriving in 5 minutes. Please meet at emergency entrance."
            },
            "Medical Updates": {
                "Vitals Update": "📊 VITALS UPDATE: BP {bp}, HR {hr}, SpO2 {spo2}. Patient condition {condition}.",
                "Medication Administered": "💊 MEDICATION: Administered {medication}. Patient response: {response}.",
                "Condition Change": "🔄 CONDITION CHANGE: Patient condition has {change}. New symptoms: {symptoms}."
            }
        }
        
        selected_category = st.selectbox("Select Category", list(template_categories.keys()))
        
        if selected_category:
            st.subheader(f"{selected_category} Templates")
            
            for template_name, template_content in template_categories[selected_category].items():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.text_area(f"{template_name}", template_content, height=100, key=f"template_{template_name}")
                with col2:
                    if st.button("Use", key=f"use_{template_name}", use_container_width=True):
                        st.session_state.selected_template = template_content
                        st.success("Template copied to message composer!")
                with col3:
                    if st.button("Edit", key=f"edit_{template_name}", use_container_width=True):
                        st.session_state.editing_template = template_name
        
        st.subheader("Create Custom Template")
        with st.form("custom_template_form"):
            template_name = st.text_input("Template Name")
            template_content = st.text_area("Template Content", height=100)
            category = st.selectbox("Category", list(template_categories.keys()) + ["Custom"])
            
            if st.form_submit_button("Save Template", use_container_width=True):
                if template_name and template_content:
                    st.success(f"Template '{template_name}' saved successfully!")
                else:
                    st.error("Please provide both template name and content")

    def _notification_log(self):
        st.subheader("📊 Notification Statistics")
        
        with self.db_service.get_session() as session:
            communications = session.query(Communication).all()
            
            if not communications:
                st.info("No notifications found")
                return
            
            total_messages = len(communications)
            automatic_messages = len([c for c in communications if c.sender == 'System'])
            driver_messages = len([c for c in communications if c.sender == 'Driver'])
            manual_messages = total_messages - automatic_messages - driver_messages
            
            today = datetime.now().date()
            today_messages = len([c for c in communications if c.timestamp.date() == today])
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Messages", total_messages)
            with col2:
                st.metric("Automatic Notifications", automatic_messages)
            with col3:
                st.metric("Driver Messages", driver_messages)
            with col4:
                st.metric("Today's Messages", today_messages)
            
            st.subheader("Message Type Distribution")
            message_types = {}
            for comm in communications:
                msg_type = comm.message_type or 'unknown'
                message_types[msg_type] = message_types.get(msg_type, 0) + 1
            
            if message_types:
                fig = px.pie(values=list(message_types.values()), names=list(message_types.keys()),
                            title="Message Types Distribution")
                st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Recent Notification Activity")
            recent_comms = sorted(communications, key=lambda x: x.timestamp, reverse=True)[:10]
            
            for comm in recent_comms:
                status_color = "🟢" if comm.sender == 'System' else "🔵" if comm.sender == 'Driver' else "🟡"
                st.write(f"{status_color} **{comm.timestamp.strftime('%H:%M')}** - {comm.sender} → {comm.receiver}: {comm.message_type}")

# Enhanced Driver UI
class DriverUI:
    def __init__(self, db_service: DatabaseService, notification_service: NotificationService):
        self.db_service = db_service
        self.notification_service = notification_service
        self.location_simulator = LocationSimulator(db_service)
    
    def display_driver_dashboard(self):
        st.header("🚑 Ambulance Driver Dashboard")
        driver_name = st.session_state.user.get('name', st.session_state.user['role'])
        
        with self.db_service.get_session() as session:
            ambulance = session.query(Ambulance).filter(Ambulance.driver_name == driver_name).first()
            
            if not ambulance:
                st.error("No ambulance assigned to you")
                return
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Ambulance ID", ambulance.ambulance_id)
            with col2:
                st.metric("Status", ambulance.status)
            with col3:
                st.metric("Location", ambulance.current_location)
            
            st.subheader("📨 Recent Notifications")
            driver_notifications = session.query(Communication).filter(
                Communication.receiver == driver_name
            ).order_by(Communication.timestamp.desc()).limit(5).all()
            
            if driver_notifications:
                for notification in driver_notifications:
                    with st.expander(f"📬 {notification.timestamp.strftime('%H:%M')} - {notification.sender}", expanded=False):
                        st.write(notification.message)
                        if notification.patient_id:
                            patient = session.query(Patient).filter(Patient.patient_id == notification.patient_id).first()
                            if patient:
                                st.write(f"**Patient:** {patient.name} - {patient.condition}")
                            
                        if notification.message_type == 'auto_driver_assignment' and ambulance.status == 'Available':
                            if st.button("Accept Assignment", key=f"accept_{notification.id}", use_container_width=True):
                                ambulance.status = 'On Transfer'
                                session.commit()
                                st.success("Assignment accepted! Proceed to patient location.")
                                st.rerun()
            else:
                st.info("No recent notifications")
            
            if ambulance.current_patient and ambulance.status == 'On Transfer':
                patient = session.query(Patient).filter(Patient.patient_id == ambulance.current_patient).first()
                if patient:
                    self._display_current_mission(ambulance, patient, session)
            
            elif ambulance.status == 'Available':
                st.info("Awaiting assignment...")
                available_patients = session.query(Patient).filter(
                    Patient.status == 'Referred',
                    Patient.assigned_ambulance.is_(None)
                ).all()
                
                if available_patients:
                    st.subheader("Available Missions")
                    for patient in available_patients:
                        with st.expander(f"Mission: {patient.name} - {patient.condition}"):
                            st.write(f"**From:** {patient.referring_hospital}")
                            st.write(f"**To:** {patient.receiving_hospital}")
                            if st.button("Accept Mission", key=f"accept_{patient.patient_id}", use_container_width=True):
                                ambulance.current_patient = patient.patient_id
                                ambulance.status = 'On Transfer'
                                patient.assigned_ambulance = ambulance.ambulance_id
                                patient.status = 'Ambulance Dispatched'
                                session.commit()
                                
                                # Start simulation for demo
                                if patient.referring_hospital_lat and patient.receiving_hospital_lat:
                                    thread = threading.Thread(
                                        target=self.location_simulator.start_simulation,
                                        args=(
                                            ambulance.ambulance_id,
                                            patient.patient_id,
                                            ambulance.latitude or patient.referring_hospital_lat,
                                            ambulance.longitude or patient.referring_hospital_lng,
                                            patient.receiving_hospital_lat,
                                            patient.receiving_hospital_lng
                                        )
                                    )
                                    thread.daemon = True
                                    thread.start()
                                
                                st.success(f"Mission accepted! Assigned to patient {patient.name}")
                                st.rerun()
            
            st.subheader("Quick Status Updates")
            self._quick_actions(ambulance, session)

    def _display_current_mission(self, ambulance, patient, session):
        st.subheader("Current Mission")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Patient:** {patient.name}")
            st.write(f"**Gender:** {patient.gender}")
            st.write(f"**Condition:** {patient.condition}")
            st.write(f"**From:** {patient.referring_hospital}")
            st.write(f"**To:** {patient.receiving_hospital}")
            st.write(f"**Status:** {patient.status}")
        
        with col2:
            st.subheader("📍 Real-time Location Sharing")
            
            if ambulance.latitude and ambulance.longitude:
                # Create enhanced map with real coordinates
                map_data = []
                
                # Add ambulance location (RED)
                map_data.append({
                    'lat': ambulance.latitude,
                    'lon': ambulance.longitude,
                    'name': f'Ambulance: {ambulance.ambulance_id}',
                    'color': 'red'
                })
                
                # Add referring hospital location (BLUE)
                if patient.referring_hospital_lat and patient.referring_hospital_lng:
                    map_data.append({
                        'lat': patient.referring_hospital_lat,
                        'lon': patient.referring_hospital_lng,
                        'name': f'Pickup: {patient.referring_hospital}',
                        'color': 'blue'
                    })
                
                # Add receiving hospital location (GREEN)
                if patient.receiving_hospital_lat and patient.receiving_hospital_lng:
                    map_data.append({
                        'lat': patient.receiving_hospital_lat,
                        'lon': patient.receiving_hospital_lng,
                        'name': f'Destination: {patient.receiving_hospital}',
                        'color': 'green'
                    })
                
                df_map = pd.DataFrame(map_data)
                
                # Use Pydeck for better visualization
                layer = pdk.Layer(
                    'ScatterplotLayer',
                    data=df_map,
                    get_position='[lon, lat]',
                    get_color='color',
                    get_radius=200,
                    pickable=True
                )
                
                view_state = pdk.ViewState(
                    latitude=ambulance.latitude,
                    longitude=ambulance.longitude,
                    zoom=12,
                    pitch=0
                )
                
                r = pdk.Deck(
                    layers=[layer],
                    initial_view_state=view_state,
                    tooltip={
                        'html': '<b>{name}</b>',
                        'style': {
                            'color': 'white'
                        }
                    }
                )
                
                st.pydeck_chart(r)
            
            st.subheader("📍 Update Location")
            with st.form("location_update_form"):
                new_lat = st.number_input("Latitude", value=ambulance.latitude or -0.0916)
                new_lng = st.number_input("Longitude", value=ambulance.longitude or 34.7680)
                location_name = st.text_input("Location Name", value=ambulance.current_location or "En route")
                
                if st.form_submit_button("Update Location", use_container_width=True):
                    ambulance_service = AmbulanceService(self.db_service)
                    if ambulance_service.update_ambulance_location(
                        ambulance.ambulance_id, new_lat, new_lng, location_name, patient.patient_id
                    ):
                        st.success("Location updated! Hospitals can now see your current position.")
        
        st.subheader("💬 Real-time Communication")
        self._display_communication_panel(patient, ambulance, session)
        
        st.subheader("Quick Actions")
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📝 Update Vitals", use_container_width=True):
                self._show_vitals_form(patient, session)
        with col2:
            if st.button("📍 Update Location", use_container_width=True):
                self._update_location_form(ambulance)
        with col3:
            if st.button("🆘 Emergency", use_container_width=True, type="secondary"):
                self._send_emergency_alert(ambulance, patient, session)
        
        st.subheader("Mission Completion")
        if st.button("✅ Mark Patient Delivered", use_container_width=True, type="primary"):
            referral_service = ReferralService(self.db_service, self.notification_service)
            if referral_service.complete_mission(ambulance.ambulance_id, patient.patient_id):
                st.rerun()

    def _display_communication_panel(self, patient, ambulance, session):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Chat with Hospitals")
            
            communications = session.query(Communication).filter(
                Communication.patient_id == patient.patient_id
            ).order_by(Communication.timestamp.desc()).limit(5).all()
            
            if communications:
                st.write("**Recent Messages:**")
                for comm in communications:
                    timestamp = comm.timestamp.strftime('%H:%M')
                    if comm.sender == 'Driver':
                        st.markdown(f"**You** ({timestamp}): {comm.message}")
                    else:
                        st.markdown(f"**{comm.sender}** ({timestamp}): {comm.message}")
            else:
                st.info("No messages yet")
            
            with st.form("message_form"):
                message = st.text_area("Type your message", placeholder="Update on patient condition, ETA, or any issues...")
                recipient = st.selectbox("Send to", 
                    [patient.referring_hospital, patient.receiving_hospital, "Both Hospitals"])
                if st.form_submit_button("Send Message", use_container_width=True):
                    if message:
                        if recipient == "Both Hospitals":
                            hospitals = [patient.referring_hospital, patient.receiving_hospital]
                        else:
                            hospitals = [recipient]
                        
                        for hospital in hospitals:
                            comm_data = {
                                'patient_id': patient.patient_id,
                                'ambulance_id': ambulance.ambulance_id,
                                'sender': 'Driver',
                                'receiver': hospital,
                                'message': message,
                                'message_type': 'driver_hospital'
                            }
                            communication = Communication(**comm_data)
                            session.add(communication)
                        
                        session.commit()
                        st.success("Message sent!")
                        st.rerun()
                    else:
                        st.error("Please enter a message")
        
        with col2:
            st.subheader("Quick Updates")
            
            quick_messages = {
                "ETA 10 mins": "Estimated arrival in 10 minutes",
                "Patient stable": "Patient condition is stable during transport",
                "Traffic delay": "Experiencing traffic delays, will update ETA",
                "Need assistance": "Require medical assistance upon arrival",
                "Vitals normal": "Patient vital signs are within normal range"
            }
            
            for label, message in quick_messages.items():
                if st.button(label, key=f"quick_{label}", use_container_width=True):
                    for hospital in [patient.referring_hospital, patient.receiving_hospital]:
                        comm_data = {
                            'patient_id': patient.patient_id,
                            'ambulance_id': ambulance.ambulance_id,
                            'sender': 'Driver',
                            'receiver': hospital,
                            'message': f"Quick update: {message}",
                            'message_type': 'driver_hospital'
                        }
                        communication = Communication(**comm_data)
                        session.add(communication)
                    session.commit()
                    st.success("Quick update sent!")

    def _show_vitals_form(self, patient, session):
        with st.form("vitals_form"):
            st.subheader("Update Patient Vitals")
            bp = st.text_input("Blood Pressure", value="120/80")
            heart_rate = st.number_input("Heart Rate (bpm)", min_value=0, max_value=200, value=72)
            spo2 = st.number_input("Oxygen Saturation (%)", min_value=0, max_value=100, value=98)
            respiratory_rate = st.number_input("Respiratory Rate", min_value=0, max_value=60, value=16)
            notes = st.text_area("Observations")
            if st.form_submit_button("Update Vitals", use_container_width=True):
                patient.vital_signs = {
                    'blood_pressure': bp, 
                    'heart_rate': heart_rate, 
                    'oxygen_saturation': spo2,
                    'respiratory_rate': respiratory_rate,
                    'notes': notes, 
                    'timestamp': datetime.utcnow().isoformat()
                }
                session.commit()
                
                for hospital in [patient.referring_hospital, patient.receiving_hospital]:
                    comm_data = {
                        'patient_id': patient.patient_id,
                        'sender': 'Driver',
                        'receiver': hospital,
                        'message': f"Vitals updated: BP {bp}, HR {heart_rate}bpm, SpO2 {spo2}%",
                        'message_type': 'vitals_update'
                    }
                    communication = Communication(**comm_data)
                    session.add(communication)
                
                session.commit()
                st.success("Vitals updated and notified hospitals!")

    def _update_location_form(self, ambulance):
        with st.form("location_form"):
            st.subheader("Update Current Location")
            location_name = st.text_input("Location Name", value=ambulance.current_location)
            latitude = st.number_input("Latitude", value=ambulance.latitude or -0.0916)
            longitude = st.number_input("Longitude", value=ambulance.longitude or 34.7680)
            if st.form_submit_button("Update Location", use_container_width=True):
                ambulance_service = AmbulanceService(self.db_service)
                if ambulance_service.update_ambulance_location(
                    ambulance.ambulance_id, latitude, longitude, location_name, ambulance.current_patient
                ):
                    st.success("Location updated! Hospitals can now see your current position.")

    def _send_emergency_alert(self, ambulance, patient, session):
        st.error("🚨 EMERGENCY ALERT SENT!")
        emergency_message = f"EMERGENCY: Ambulance {ambulance.ambulance_id} requires immediate assistance!"
        
        recipients = [patient.referring_hospital, patient.receiving_hospital, "Control Center"]
        for recipient in recipients:
            comm_data = {
                'patient_id': patient.patient_id,
                'ambulance_id': ambulance.ambulance_id,
                'sender': 'Driver',
                'receiver': recipient,
                'message': emergency_message,
                'message_type': 'emergency'
            }
            communication = Communication(**comm_data)
            session.add(communication)
        
        session.commit()

    def _quick_actions(self, ambulance, session):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🔄 Mark Available", use_container_width=True):
                ambulance.status = 'Available'
                ambulance.current_patient = None
                session.commit()
                st.success("Status updated to Available")
                st.rerun()
        with col2:
            if st.button("⛑️ Mark On Break", use_container_width=True):
                ambulance.status = 'On Break'
                session.commit()
                st.success("Status updated to On Break")
                st.rerun()
        with col3:
            if st.button("🔧 Maintenance", use_container_width=True):
                ambulance.status = 'Maintenance'
                session.commit()
                st.success("Status updated to Maintenance")
                st.rerun()

# Enhanced Handover UI with PDF Generation
class HandoverUI:
    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
    
    def display(self):
        st.title("📄 Patient Handover Management")
        
        tab1, tab2, tab3 = st.tabs(["Create Handover Form", "Handover History", "Download Reports"])
        
        with tab1:
            self._create_handover_form()
        with tab2:
            self._display_handover_history()
        with tab3:
            self._download_reports()

    def _create_handover_form(self):
        st.subheader("Create Handover Form")
        
        with self.db_service.get_session() as session:
            user_hospital = st.session_state.user['hospital']
            
            if user_hospital == "All Facilities":
                eligible_patients = session.query(Patient).filter(Patient.status == 'Arrived at Destination').all()
            else:
                eligible_patients = session.query(Patient).filter(
                    Patient.receiving_hospital == user_hospital, 
                    Patient.status == 'Arrived at Destination'
                ).all()
                
            if not eligible_patients:
                st.info("No patients eligible for handover (must have status 'Arrived at Destination')")
                return
            
            patient_options = {f"{p.patient_id} - {p.name}": p for p in eligible_patients}
            selected_patient_key = st.selectbox("Select Patient", list(patient_options.keys()))
            selected_patient = patient_options[selected_patient_key]
            
            with st.form("handover_form", clear_on_submit=True):
                st.write(f"**Patient:** {selected_patient.name}")
                st.write(f"**Gender:** {selected_patient.gender}")
                st.write(f"**Condition:** {selected_patient.condition}")
                st.write(f"**From:** {selected_patient.referring_hospital}")
                st.write(f"**To:** {selected_patient.receiving_hospital}")
                
                # Display cost information
                if selected_patient.trip_distance:
                    cost_service = CostCalculationService(self.db_service)
                    cost_info = cost_service.calculate_trip_cost(selected_patient.trip_distance)
                    
                    st.subheader("📊 Trip Cost Summary")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Distance", f"{selected_patient.trip_distance} km")
                    with col2:
                        st.metric("Fuel Cost", f"KSh {cost_info['fuel_cost_ksh']:,.0f}")
                    with col3:
                        st.metric("Total Cost", f"KSh {cost_info['total_cost_ksh']:,.0f}")
                
                st.subheader("Vital Signs at Handover")
                col1, col2 = st.columns(2)
                with col1:
                    blood_pressure = st.text_input("Blood Pressure", value="120/80")
                    heart_rate = st.number_input("Heart Rate (bpm)", min_value=0, max_value=200, value=72)
                with col2:
                    temperature = st.number_input("Temperature (°C)", min_value=30.0, max_value=45.0, value=36.6)
                    oxygen_saturation = st.number_input("Oxygen Saturation (%)", min_value=0, max_value=100, value=98)
                
                st.subheader("Handover Details")
                receiving_physician = st.text_input("Receiving Physician*")
                handover_notes = st.text_area("Handover Notes")
                
                with st.expander("Additional Information"):
                    condition_changes = st.text_area("Condition Changes During Transfer")
                    interventions = st.text_area("Interventions During Transfer")
                    medications_administered = st.text_area("Medications Administered")
                
                submitted = st.form_submit_button("Complete Handover", use_container_width=True)
                if submitted:
                    if not receiving_physician:
                        st.error("Please enter the receiving physician")
                    else:
                        # Calculate final costs
                        distance_covered = selected_patient.trip_distance or 0
                        cost_service = CostCalculationService(self.db_service)
                        cost_info = cost_service.calculate_trip_cost(distance_covered)
                        
                        handover_data = {
                            'patient_id': selected_patient.patient_id,
                            'patient_name': selected_patient.name,
                            'age': selected_patient.age,
                            'gender': selected_patient.gender,
                            'condition': selected_patient.condition,
                            'referring_hospital': selected_patient.referring_hospital,
                            'receiving_hospital': selected_patient.receiving_hospital,
                            'referring_physician': selected_patient.referring_physician,
                            'receiving_physician': receiving_physician,
                            'vital_signs': {
                                'blood_pressure': blood_pressure,
                                'heart_rate': heart_rate,
                                'temperature': temperature,
                                'oxygen_saturation': oxygen_saturation
                            },
                            'medical_history': selected_patient.medical_history,
                            'current_medications': selected_patient.current_medications,
                            'allergies': selected_patient.allergies,
                            'notes': handover_notes,
                            'ambulance_id': selected_patient.assigned_ambulance,
                            'created_by': st.session_state.user['id'],
                            'distance_covered': distance_covered,
                            'fuel_cost': cost_info['fuel_cost_ksh'],
                            'total_cost': cost_info['total_cost_ksh']
                        }
                        handover = HandoverForm(**handover_data)
                        session.add(handover)
                        
                        selected_patient.status = 'Completed'
                        selected_patient.receiving_physician = receiving_physician
                        session.commit()
                        
                        st.success("Handover completed successfully!")
                        st.balloons()

    def _display_handover_history(self):
        st.subheader("Handover History")
        
        with self.db_service.get_session() as session:
            user_hospital = st.session_state.user['hospital']
            
            if user_hospital != "All Facilities":
                handovers = session.query(HandoverForm).filter(
                    HandoverForm.receiving_hospital == user_hospital
                ).all()
            else:
                handovers = session.query(HandoverForm).all()
                
            if handovers:
                for handover in handovers:
                    with st.expander(f"{handover.patient_name} - {handover.transfer_time.strftime('%Y-%m-%d %H:%M')}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Patient ID:** {handover.patient_id}")
                            st.write(f"**Age:** {handover.age}")
                            st.write(f"**Gender:** {handover.gender}")
                            st.write(f"**Condition:** {handover.condition}")
                            st.write(f"**Referring Hospital:** {handover.referring_hospital}")
                            st.write(f"**Receiving Hospital:** {handover.receiving_hospital}")
                        with col2:
                            st.write(f"**Referring Physician:** {handover.referring_physician}")
                            st.write(f"**Receiving Physician:** {handover.receiving_physician}")
                            st.write(f"**Ambulance:** {handover.ambulance_id}")
                            st.write(f"**Handover Time:** {handover.transfer_time.strftime('%Y-%m-%d %H:%M')}")
                            if handover.distance_covered:
                                st.write(f"**Distance Covered:** {handover.distance_covered} km")
                            if handover.total_cost:
                                st.write(f"**Total Cost:** KSh {handover.total_cost:,.0f}")
                        
                        if handover.vital_signs:
                            st.subheader("Vital Signs at Handover")
                            vitals = handover.vital_signs
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("BP", vitals.get('blood_pressure', 'N/A'))
                            with col2:
                                st.metric("HR", f"{vitals.get('heart_rate', 'N/A')} bpm")
                            with col3:
                                st.metric("Temp", f"{vitals.get('temperature', 'N/A')}°C")
                            with col4:
                                st.metric("SpO2", f"{vitals.get('oxygen_saturation', 'N/A')}%")
                        
                        if handover.notes:
                            st.write(f"**Handover Notes:** {handover.notes}")
            else:
                st.info("No handover forms completed")

    def _download_reports(self):
        st.subheader("📊 Download Handover Reports")
        
        with self.db_service.get_session() as session:
            handovers = session.query(HandoverForm).all()
            
            if not handovers:
                st.info("No handover data available for download")
                return
            
            # CSV Download
            st.download_button(
                label="📄 Download Handover Data as CSV",
                data=self._export_handovers_csv(handovers),
                file_name=f"handover_reports_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            # PDF Generation
            if st.button("📋 Generate PDF Report", use_container_width=True):
                pdf_data = self._generate_pdf_report(handovers)
                st.download_button(
                    label="⬇️ Download PDF Report",
                    data=pdf_data,
                    file_name=f"handover_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

    def _export_handovers_csv(self, handovers):
        data = []
        for handover in handovers:
            data.append({
                'Patient ID': handover.patient_id,
                'Patient Name': handover.patient_name,
                'Age': handover.age,
                'Gender': handover.gender,
                'Condition': handover.condition,
                'Referring Hospital': handover.referring_hospital,
                'Receiving Hospital': handover.receiving_hospital,
                'Referring Physician': handover.referring_physician,
                'Receiving Physician': handover.receiving_physician,
                'Ambulance ID': handover.ambulance_id,
                'Distance Covered (km)': handover.distance_covered,
                'Total Cost (KSh)': handover.total_cost,
                'Handover Time': handover.transfer_time.strftime('%Y-%m-%d %H:%M')
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)

    def _generate_pdf_report(self, handovers):
        """Generate PDF report for handovers"""
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        import io
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title = Paragraph("Kisumu County Hospital - Handover Report", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # Summary
        summary = Paragraph(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}<br/>Total Handovers: {len(handovers)}", styles['Normal'])
        story.append(summary)
        story.append(Spacer(1, 12))
        
        # Table data
        data = [['Patient', 'Hospital', 'Distance (km)', 'Cost (KSh)', 'Time']]
        total_distance = 0
        total_cost = 0
        
        for handover in handovers:
            data.append([
                handover.patient_name,
                handover.receiving_hospital,
                f"{handover.distance_covered or 0:.1f}",
                f"{handover.total_cost or 0:,.0f}",
                handover.transfer_time.strftime('%m/%d %H:%M')
            ])
            total_distance += handover.distance_covered or 0
            total_cost += handover.total_cost or 0
        
        # Add totals row
        data.append(['TOTAL', '', f"{total_distance:.1f}", f"{total_cost:,.0f}", ''])
        
        # Create table
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        doc.build(story)
        
        buffer.seek(0)
        return buffer.getvalue()

# Enhanced Reports UI with Analytics Export
class ReportsUI:
    def __init__(self, db_service: DatabaseService, analytics_service: AnalyticsService):
        self.db_service = db_service
        self.analytics = analytics_service
    
    def display(self):
        st.title("📈 Reports & Analytics")
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["Performance Metrics", "Hospital Analytics", "Ambulance Reports", "Cost Analytics", "Export Data"])
        
        with tab1:
            self._performance_metrics()
        with tab2:
            self._hospital_analytics()
        with tab3:
            self._ambulance_reports()
        with tab4:
            self._cost_analytics()
        with tab5:
            self._export_data()

    def _performance_metrics(self):
        st.subheader("Performance Metrics")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", datetime.now() - timedelta(days=30))
        with col2:
            end_date = st.date_input("End Date", datetime.now())
        
        kpis = self.analytics.get_kpis()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Referrals", kpis['total_referrals'])
        with col2:
            st.metric("Completion Rate", kpis['completion_rate'])
        with col3:
            st.metric("Avg Response Time", kpis['avg_response_time'])
        with col4:
            st.metric("Active Transfers", kpis['active_referrals'])
        
        st.subheader("Response Time Trends")
        trends_data = self.analytics.get_referral_trends()
        if not trends_data.empty:
            fig = px.line(trends_data, x='date', y='count', title="Referral Trends")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No trend data available")
        
        st.subheader("Referral Reasons")
        with self.db_service.get_session() as session:
            patients = session.query(Patient).all()
            if patients:
                conditions = [p.condition for p in patients]
                condition_counts = pd.Series(conditions).value_counts()
                fig = px.pie(values=condition_counts.values, names=condition_counts.index,
                            title="Referral Reasons Distribution")
                st.plotly_chart(fig, use_container_width=True)

    def _hospital_analytics(self):
        st.subheader("Hospital Performance")
        hospitals_stats = self.analytics.get_hospital_stats()
        if not hospitals_stats.empty:
            hospital_referrals = hospitals_stats.groupby('hospital')['count'].sum().reset_index()
            fig = px.bar(hospital_referrals, x='hospital', y='count', title="Total Referrals by Hospital")
            st.plotly_chart(fig, use_container_width=True)
            
            fig = px.sunburst(hospitals_stats, path=['hospital', 'status'], values='count',
                             title="Referral Status by Hospital")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hospital data available")

    def _ambulance_reports(self):
        st.subheader("Ambulance Utilization")
        with self.db_service.get_session() as session:
            ambulances = session.query(Ambulance).all()
            if ambulances:
                status_counts = {}
                for ambulance in ambulances:
                    status_counts[ambulance.status] = status_counts.get(ambulance.status, 0) + 1
                
                fig = px.pie(values=list(status_counts.values()), names=list(status_counts.keys()),
                            title="Ambulance Status Distribution")
                st.plotly_chart(fig, use_container_width=True)
                
                st.subheader("Ambulance Utilization Details")
                ambulance_data = []
                for ambulance in ambulances:
                    utilization = "High" if ambulance.status != 'Available' else "Low"
                    ambulance_data.append({
                        'Ambulance ID': ambulance.ambulance_id,
                        'Driver': ambulance.driver_name,
                        'Status': ambulance.status,
                        'Utilization': utilization,
                        'Current Patient': ambulance.current_patient or 'None',
                        'Location': ambulance.current_location,
                        'Fuel Level': f"{ambulance.fuel_level:.1f}%",
                        'Total Distance': f"{ambulance.total_distance_traveled:,.1f} km",
                        'Total Cost': f"KSh {ambulance.total_fuel_cost:,.0f}"
                    })
                st.dataframe(pd.DataFrame(ambulance_data), use_container_width=True)
            else:
                st.info("No ambulance data available")

    def _cost_analytics(self):
        st.subheader("Cost Analytics")
        cost_data = self.analytics.get_cost_analytics()
        
        if cost_data['total_trip_costs'] > 0:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Trip Costs", f"KSh {cost_data['total_trip_costs']:,.0f}")
            with col2:
                st.metric("Total Savings", f"KSh {cost_data['total_trip_savings']:,.0f}")
            with col3:
                st.metric("Net Cost", f"KSh {cost_data['total_trip_costs'] - cost_data['total_trip_savings']:,.0f}")
            
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=cost_data['months'],
                y=cost_data['monthly_costs'],
                name='Costs',
                marker_color='red'
            ))
            fig.add_trace(go.Bar(
                x=cost_data['months'],
                y=cost_data['monthly_savings'],
                name='Savings',
                marker_color='green'
            ))
            fig.update_layout(
                title='Monthly Costs vs Savings',
                barmode='group',
                xaxis_title='Month',
                yaxis_title='Amount (KSh)'
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No cost data available yet")

    def _export_data(self):
        st.subheader("Data Export")
        
        col1, col2 = st.columns(2)
        with col1:
            # CSV Exports
            st.download_button(
                label="📊 Export Referrals as CSV",
                data=self._export_referrals_csv(),
                file_name=f"referrals_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            st.download_button(
                label="🚑 Export Ambulance Data as CSV",
                data=self._export_ambulances_csv(),
                file_name=f"ambulances_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            st.download_button(
                label="💰 Export Cost Data as CSV",
                data=self._export_cost_data_csv(),
                file_name=f"cost_data_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col2:
            # PDF Reports
            if st.button("📄 Generate Comprehensive PDF Report", use_container_width=True):
                pdf_data = self._generate_comprehensive_pdf()
                st.download_button(
                    label="⬇️ Download PDF Report",
                    data=pdf_data,
                    file_name=f"comprehensive_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            
            if st.button("📈 Export Analytics Dashboard", use_container_width=True):
                analytics_data = self._export_analytics_data()
                st.download_button(
                    label="⬇️ Download Analytics Data",
                    data=analytics_data,
                    file_name=f"analytics_export_{datetime.now().strftime('%Y%m%d')}.json",
                    mime="application/json",
                    use_container_width=True
                )

    def _export_referrals_csv(self):
        with self.db_service.get_session() as session:
            patients = session.query(Patient).all()
            data = []
            for patient in patients:
                data.append({
                    'Patient ID': patient.patient_id,
                    'Name': patient.name,
                    'Age': patient.age,
                    'Gender': patient.gender,
                    'Condition': patient.condition,
                    'Referring Hospital': patient.referring_hospital,
                    'Receiving Hospital': patient.receiving_hospital,
                    'Status': patient.status,
                    'Referral Time': patient.referral_time,
                    'Assigned Ambulance': patient.assigned_ambulance,
                    'Trip Distance': patient.trip_distance,
                    'Trip Cost': patient.trip_fuel_cost,
                    'Actual Distance Covered': patient.actual_distance_covered
                })
            df = pd.DataFrame(data)
            return df.to_csv(index=False)

    def _export_ambulances_csv(self):
        with self.db_service.get_session() as session:
            ambulances = session.query(Ambulance).all()
            data = []
            for ambulance in ambulances:
                data.append({
                    'Ambulance ID': ambulance.ambulance_id,
                    'Driver': ambulance.driver_name,
                    'Contact': ambulance.driver_contact,
                    'Status': ambulance.status,
                    'Location': ambulance.current_location,
                    'Current Patient': ambulance.current_patient,
                    'Fuel Level': ambulance.fuel_level,
                    'Total Distance': ambulance.total_distance_traveled,
                    'Total Cost': ambulance.total_fuel_cost,
                    'Cost Savings': ambulance.cost_savings
                })
            df = pd.DataFrame(data)
            return df.to_csv(index=False)

    def _export_cost_data_csv(self):
        with self.db_service.get_session() as session:
            patients = session.query(Patient).filter(Patient.status == 'Completed').all()
            data = []
            for patient in patients:
                if patient.trip_distance and patient.trip_fuel_cost:
                    data.append({
                        'Patient ID': patient.patient_id,
                        'Patient Name': patient.name,
                        'Distance (km)': patient.trip_distance,
                        'Fuel Cost (KSh)': patient.trip_fuel_cost,
                        'Cost Savings (KSh)': patient.trip_cost_savings,
                        'Referring Hospital': patient.referring_hospital,
                        'Receiving Hospital': patient.receiving_hospital,
                        'Completion Time': patient.updated_at
                    })
            df = pd.DataFrame(data)
            return df.to_csv(index=False)

    def _generate_comprehensive_pdf(self):
        """Generate a comprehensive PDF report"""
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        import io
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title = Paragraph("Kisumu County Hospital - Comprehensive Report", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # Summary
        kpis = self.analytics.get_kpis()
        summary_text = f"""
        Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        Total Referrals: {kpis['total_referrals']}
        Active Transfers: {kpis['active_referrals']}
        Available Ambulances: {kpis['available_ambulances']}
        Total Fuel Cost: KSh {kpis['total_fuel_cost']:,.0f}
        Total Savings: KSh {kpis['total_cost_savings']:,.0f}
        """
        summary = Paragraph(summary_text, styles['Normal'])
        story.append(summary)
        story.append(Spacer(1, 12))
        
        # Cost Summary Table
        cost_data = self.analytics.get_cost_analytics()
        if cost_data['total_trip_costs'] > 0:
            cost_table_data = [
                ['Metric', 'Value'],
                ['Total Trip Costs', f"KSh {cost_data['total_trip_costs']:,.0f}"],
                ['Total Savings', f"KSh {cost_data['total_trip_savings']:,.0f}"],
                ['Net Cost', f"KSh {cost_data['total_trip_costs'] - cost_data['total_trip_savings']:,.0f}"],
                ['Cost Efficiency', f"{(cost_data['total_trip_savings'] / cost_data['total_trip_costs'] * 100) if cost_data['total_trip_costs'] > 0 else 0:.1f}%"]
            ]
            
            cost_table = Table(cost_table_data)
            cost_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(Paragraph("Cost Summary", styles['Heading2']))
            story.append(cost_table)
            story.append(Spacer(1, 12))
        
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()

    def _export_analytics_data(self):
        """Export analytics data as JSON"""
        import json
        
        analytics_data = {
            'timestamp': datetime.now().isoformat(),
            'kpis': self.analytics.get_kpis(),
            'cost_analytics': self.analytics.get_cost_analytics(),
            'summary': {
                'total_referrals': self.analytics.get_kpis()['total_referrals'],
                'total_cost': self.analytics.get_kpis()['total_fuel_cost'],
                'total_savings': self.analytics.get_kpis()['total_cost_savings']
            }
        }
        
        return json.dumps(analytics_data, indent=2)

# Enhanced Main Application
class HospitalReferralApp:
    def __init__(self):
        self.setup_page_config()
        self.setup_services()
        self.auth = Authentication()
        
        if 'initialized' not in st.session_state:
            self.initialize_session_state()
    
    def setup_page_config(self):
        st.set_page_config(
            page_title=Config.app.page_title,
            page_icon=Config.app.page_icon,
            layout=Config.app.layout,
            initial_sidebar_state="expanded"
        )
        
        st.markdown("""
        <style>
        .main-header {
            font-size: 2.5rem;
            color: #1f77b4;
            text-align: center;
            margin-bottom: 2rem;
        }
        .metric-card {
            background-color: #f0f2f6;
            padding: 1rem;
            border-radius: 10px;
            border-left: 5px solid #1f77b4;
        }
        .stButton button {
            width: 100%;
        }
        </style>
        """, unsafe_allow_html=True)
    
    def setup_services(self):
        try:
            self.db_service = DatabaseService()
            self.notification_service = NotificationService(self.db_service)
            self.referral_service = ReferralService(self.db_service, self.notification_service)
            self.analytics_service = AnalyticsService(self.db_service)
            self.cost_service = CostCalculationService(self.db_service)
            self.ambulance_service = AmbulanceService(self.db_service)
            
            # Initialize UI components
            self.dashboard_ui = DashboardUI(self.analytics_service, self.db_service)
            self.referral_ui = ReferralUI(self.referral_service, self.db_service)
            self.cost_management_ui = CostManagementUI(self.analytics_service, self.db_service)
            self.tracking_ui = TrackingUI(self.db_service, self.cost_service)
            self.communication_ui = CommunicationUI(self.db_service, self.notification_service)
            self.handover_ui = HandoverUI(self.db_service)
            self.reports_ui = ReportsUI(self.db_service, self.analytics_service)
            self.driver_ui = DriverUI(self.db_service, self.notification_service)
            
            logger.info("Services initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing services: {str(e)}")
            st.error("Failed to initialize application services")
    
    def initialize_session_state(self):
        st.session_state.initialized = True
        st.session_state.authenticated = False
        st.session_state.user = None
        st.session_state.simulation_running = False
    
    def initialize_database(self):
        try:
            Base.metadata.create_all(engine)
            logger.info("Database tables created")
            
            self.auth.initialize_default_users()
            self.initialize_sample_data()
            
        except Exception as e:
            logger.error(f"Error initializing database: {str(e)}")
            st.error("Failed to initialize database")
    
    def initialize_sample_data(self):
        try:
            with session_scope() as session:
                ambulance_count = session.query(Ambulance).count()
                
                if ambulance_count == 0:
                    for ambulance_data in AMBULANCE_DATA:
                        ambulance = Ambulance(
                            ambulance_id=ambulance_data['ambulance_id'],
                            current_location=ambulance_data['location'],
                            latitude=ambulance_data['lat'],
                            longitude=ambulance_data['lng'],
                            status=ambulance_data['status'],
                            driver_name=ambulance_data['driver_name'],
                            driver_contact=ambulance_data['driver_contact'],
                            current_patient=ambulance_data['current_patient'],
                            fuel_level=100.0,
                            total_fuel_cost=0.0,
                            total_distance_traveled=0.0,
                            cost_savings=0.0,
                            ambulance_type="Basic Life Support",
                            equipment="Basic medical equipment"
                        )
                        session.add(ambulance)
                    
                    session.commit()
                    logger.info("Sample ambulance data initialized")
                    
        except Exception as e:
            logger.error(f"Error initializing sample data: {str(e)}")
    
    def run(self):
        try:
            self.initialize_database()
            
            self.auth.setup_auth_ui()
            
            if st.session_state.get('authenticated'):
                self.render_main_application()
            else:
                self.render_landing_page()
                
        except Exception as e:
            logger.error(f"Application error: {str(e)}")
            st.error("An unexpected error occurred. Please refresh the page.")
    
    def render_landing_page(self):
        st.title("🏥 Kisumu County Hospital Referral System")
        
        st.markdown("""
        ## Welcome to the Hospital Referral & Ambulance Tracking System
        
        Please login using the sidebar to access the system.
        
        **Key Features:**
        - 🚑 Real-time ambulance tracking with cost analysis
        - 💰 Advanced cost management and analytics
        - 📊 Performance monitoring with automatic notifications
        - 📱 Enhanced communication center
        - 📈 Comprehensive reporting with cost tracking
        
        **System Benefits:**
        - Reduced Response Time: Average response time under 15 minutes
        - Cost Efficiency: Up to 20% savings through optimized routing and fuel management
        - Real-time Tracking: Live ambulance location and status updates with cost analysis
        - Automated Communication: Instant notifications to all stakeholders with message templates
        """)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Hospitals in Network", len(HOSPITAL_LOCATIONS))
        with col2:
            st.metric("Ambulance Fleet", len(AMBULANCE_DATA))
        with col3:
            st.metric("Coverage Area", "Kisumu County")
    
    def render_main_application(self):
        self.render_user_info()
        
        user_role = st.session_state.user['role']
        
        if user_role == 'Admin':
            self.render_admin_interface()
        elif user_role == 'Hospital Staff':
            self.render_staff_interface()
        elif user_role == 'Ambulance Driver':
            self.render_driver_interface()
        
        st.markdown("---")
        st.markdown(
            "**Kisumu County Hospital Referral System** | "
            "Secure • Reliable • Cost-Efficient"
        )
    
    def render_user_info(self):
        st.sidebar.markdown("---")
        user = st.session_state.user
        
        st.sidebar.success(f"**Logged in as:** {user['name']}")
        st.sidebar.write(f"**Role:** {user['role']}")
        st.sidebar.write(f"**Hospital:** {user['hospital']}")
        
        if user.get('last_login'):
            last_login = user['last_login'].strftime('%Y-%m-%d %H:%M')
            st.sidebar.write(f"**Last Login:** {last_login}")
    
    def render_admin_interface(self):
        st.sidebar.title("Admin Navigation")
        
        pages = {
            "📊 Dashboard": self.render_dashboard,
            "📋 Referrals": self.render_referrals,
            "💰 Cost Management": self.render_cost_management,
            "🚑 Ambulance Tracking": self.render_tracking,
            "💬 Communication": self.render_communication,
            "📄 Handovers": self.render_handovers,
            "📈 Reports": self.render_reports,
            "👥 User Management": self.render_user_management,
        }
        
        selected_page = st.sidebar.radio("Navigate to", list(pages.keys()))
        pages[selected_page]()
    
    def render_staff_interface(self):
        st.sidebar.title("Staff Navigation")
        
        pages = {
            "📊 Dashboard": self.render_dashboard,
            "📋 Referrals": self.render_referrals,
            "🚑 Ambulance Tracking": self.render_tracking,
            "💬 Communication": self.render_communication,
            "📄 Handovers": self.render_handovers
        }
        
        selected_page = st.sidebar.radio("Navigate to", list(pages.keys()))
        pages[selected_page]()
    
    def render_driver_interface(self):
        st.sidebar.title("Driver Navigation")
        
        pages = {
            "🚑 Driver Dashboard": self.render_driver_dashboard,
            "📍 Location Updates": self.render_location_updates,
            "💬 Communication": self.render_communication
        }
        
        selected_page = st.sidebar.radio("Navigate to", list(pages.keys()))
        pages[selected_page]()
    
    def render_dashboard(self):
        self.dashboard_ui.display()
    
    def render_referrals(self):
        self.referral_ui.display()
    
    def render_cost_management(self):
        self.cost_management_ui.display()
    
    def render_tracking(self):
        self.tracking_ui.display()
    
    def render_communication(self):
        self.communication_ui.display()
    
    def render_handovers(self):
        self.handover_ui.display()
    
    def render_reports(self):
        self.reports_ui.display()
    
    def render_driver_dashboard(self):
        self.driver_ui.display_driver_dashboard()
    
    def render_location_updates(self):
        st.title("📍 Location Updates")
        st.info("Driver location update interface is integrated into the Driver Dashboard")
        self.driver_ui.display_driver_dashboard()
    
    def render_user_management(self):
        st.title("👥 User Management")
        
        if not self.auth.require_auth(['Admin']):
            return
            
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Add New User")
            with st.form("add_user_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                email = st.text_input("Email")
                role = st.selectbox("Role", ["Admin", "Hospital Staff", "Ambulance Driver"])
                hospital = st.selectbox("Hospital", self.auth._get_hospital_options())
                name = st.text_input("Full Name")
                
                if st.form_submit_button("Add User", use_container_width=True):
                    if all([username, password, email, name]):
                        user_data = {
                            'username': username,
                            'email': email,
                            'password': password,
                            'role': role,
                            'hospital': hospital,
                            'name': name
                        }
                        if self.auth.register_user(user_data):
                            st.rerun()
                    else:
                        st.error("Please fill all fields")
        
        with col2:
            st.subheader("Current Users")
            with self.db_service.get_session() as session:
                users = session.query(User).all()
                if users:
                    user_data = []
                    for user in users:
                        user_data.append({
                            'Username': user.username,
                            'Name': user.name,
                            'Role': user.role,
                            'Hospital': user.hospital,
                            'Status': 'Active' if user.is_active else 'Inactive'
                        })
                    st.dataframe(pd.DataFrame(user_data), use_container_width=True)
                else:
                    st.info("No users found")

def main():
    app = HospitalReferralApp()
    app.run()


if __name__ == "__main__":
    main()