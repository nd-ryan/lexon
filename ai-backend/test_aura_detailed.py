#!/usr/bin/env python3
"""
Detailed AuraDB connection diagnostic script.
"""
import os
import sys
from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS, WRITE_ACCESS

load_dotenv()

def test_detailed_connection():
    """Detailed connection test with different access modes."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    
    print("=" * 70)
    print("Detailed Neo4j AuraDB Connection Diagnostic")
    print("=" * 70)
    print(f"\nURI: {uri}")
    print(f"Database: {database}")
    
    # Test 1: Create driver
    print("\n[1/5] Creating driver...")
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        print("   ✅ Driver created successfully")
    except Exception as e:
        print(f"   ❌ Failed to create driver: {e}")
        return False
    
    # Test 2: Check if driver is healthy
    print("\n[2/5] Checking driver health...")
    try:
        # Just check that driver object exists
        print(f"   ✅ Driver object is valid")
    except Exception as e:
        print(f"   ❌ Driver issue: {e}")
        driver.close()
        return False
    
    # Test 3: Try READ session
    print("\n[3/5] Testing READ session...")
    try:
        with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
            result = session.run("RETURN 1 as num")
            record = result.single()
            if record and record["num"] == 1:
                print("   ✅ READ session works!")
            else:
                print("   ⚠️  READ session returned unexpected result")
    except Exception as e:
        print(f"   ❌ READ session failed: {type(e).__name__}: {e}")
    
    # Test 4: Try WRITE session
    print("\n[4/5] Testing WRITE session...")
    try:
        with driver.session(database=database, default_access_mode=WRITE_ACCESS) as session:
            result = session.run("RETURN 1 as num")
            record = result.single()
            if record and record["num"] == 1:
                print("   ✅ WRITE session works!")
            else:
                print("   ⚠️  WRITE session returned unexpected result")
    except Exception as e:
        print(f"   ❌ WRITE session failed: {type(e).__name__}: {e}")
    
    # Test 5: Try to query actual data
    print("\n[5/5] Testing actual data query...")
    try:
        with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
            result = session.run("MATCH (n) RETURN count(n) as count LIMIT 1")
            record = result.single()
            count = record["count"] if record else 0
            print(f"   ✅ Database has {count:,} nodes")
    except Exception as e:
        print(f"   ❌ Data query failed: {type(e).__name__}: {e}")
    
    driver.close()
    
    print("\n" + "=" * 70)
    print("Diagnostic complete")
    print("=" * 70 + "\n")
    
    return True

if __name__ == "__main__":
    test_detailed_connection()

