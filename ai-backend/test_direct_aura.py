#!/usr/bin/env python3
"""
Direct test of AuraDB connection using only Neo4j driver.
No custom code involved.
"""
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

uri = os.getenv("NEO4J_URI")
username = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")

print("=" * 70)
print("Direct AuraDB Connection Test (No Custom Code)")
print("=" * 70)
print(f"\nConnecting to: {uri}")
print(f"Username: {username}")

try:
    # Create driver - minimal configuration
    driver = GraphDatabase.driver(uri, auth=(username, password))
    print("\n✅ Driver created")
    
    # Try to execute the simplest possible query
    print("\nAttempting query: RETURN 1 as test")
    with driver.session() as session:
        result = session.run("RETURN 1 as test")
        record = result.single()
        print(f"✅ SUCCESS! Result: {record['test']}")
        print("\n🎉 Neo4j connection is working!")
        
        # Try to get some info
        print("\nGetting database info...")
        result = session.run("CALL dbms.components() YIELD name, versions, edition")
        for record in result:
            print(f"   Name: {record['name']}")
            print(f"   Versions: {record['versions']}")
            print(f"   Edition: {record['edition']}")
    
    driver.close()
    print("\n" + "=" * 70)
    print("✅ Connection test PASSED")
    print("=" * 70)
    
except Exception as e:
    print(f"\n❌ Connection FAILED")
    print(f"\nError Type: {type(e).__name__}")
    print(f"Error Message: {str(e)}")
    print("\n" + "=" * 70)
    print("❌ Connection test FAILED")
    print("=" * 70)
    print("\n💡 This error typically means:")
    print("   1. AuraDB instance is PAUSED (most common)")
    print("   2. AuraDB instance is STOPPED")
    print("   3. Instance has been deleted")
    print("   4. Network/firewall blocking access")
    print("\n📋 Next steps:")
    print("   1. Go to: https://console.neo4j.io/")
    print("   2. Check if instance 'b63032c7' is RUNNING (green)")
    print("   3. If paused, click 'Resume' button")
    print("   4. If stopped, click 'Start' button")

