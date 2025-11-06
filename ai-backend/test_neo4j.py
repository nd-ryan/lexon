#!/usr/bin/env python3
"""
Standalone script to test Neo4j connection.
Run from the ai-backend directory: python test_neo4j.py
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_neo4j_connection():
    """Test Neo4j connection and print status."""
    try:
        print("=" * 60)
        print("Neo4j Connection Test")
        print("=" * 60)
        
        # Get connection details
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        username = os.getenv("NEO4J_USER", "neo4j")
        password_set = "Yes" if os.getenv("NEO4J_PASSWORD") else "No"
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        print(f"\n📋 Connection Configuration:")
        print(f"   URI:      {uri}")
        print(f"   Username: {username}")
        print(f"   Password: {'*' * 8 if password_set == 'Yes' else 'Not set'}")
        print(f"   Database: {database}")
        
        is_auradb = uri.startswith("neo4j+s://") or uri.startswith("neo4j+ssc://")
        print(f"   Type:     {'AuraDB (Cloud)' if is_auradb else 'Local/Self-hosted'}")
        
        print(f"\n🔌 Initializing driver...")
        
        from app.lib.neo4j_client import neo4j_client
        
        if not neo4j_client.driver:
            print("   ❌ Driver initialization failed!")
            print(f"\n{'=' * 60}")
            print("❌ Could not initialize Neo4j driver")
            print(f"{'=' * 60}\n")
            return False
        
        print("   ✅ Driver initialized")
        print(f"\n🔌 Testing connection...")
        
        # Try to execute a simple query
        result = neo4j_client.execute_query("RETURN 1 as test")
        
        if result and len(result) > 0:
            print("   ✅ Connection successful!")
            
            # Count nodes and relationships
            print(f"\n📊 Database Statistics:")
            
            node_count_result = neo4j_client.execute_query("MATCH (n) RETURN count(n) as count")
            node_count = node_count_result[0].get('count', 0) if node_count_result else 0
            print(f"   Total Nodes: {node_count:,}")
            
            rel_count_result = neo4j_client.execute_query("MATCH ()-[r]->() RETURN count(r) as count")
            rel_count = rel_count_result[0].get('count', 0) if rel_count_result else 0
            print(f"   Total Relationships: {rel_count:,}")
            
            # Get label statistics
            print(f"\n🏷️  Node Labels (Top 10):")
            try:
                labels_result = neo4j_client.execute_query("""
                    CALL db.labels() YIELD label
                    CALL {
                        WITH label
                        MATCH (n)
                        WHERE label IN labels(n)
                        RETURN count(n) as count
                    }
                    RETURN label, count
                    ORDER BY count DESC
                    LIMIT 10
                """)
                
                if labels_result:
                    for record in labels_result:
                        label = record.get('label', 'Unknown')
                        count = record.get('count', 0)
                        print(f"   {label:20s} {count:,}")
                else:
                    print("   No labels found")
            except Exception as e:
                print(f"   Could not fetch label statistics: {e}")
            
            print(f"\n{'=' * 60}")
            print("✅ Neo4j is connected and working!")
            print(f"{'=' * 60}\n")
            return True
        else:
            print("   ❌ Connection failed - no results returned")
            return False
            
    except Exception as e:
        print(f"   ❌ Connection failed!")
        print(f"\n⚠️  Error Details:")
        print(f"   Type: {type(e).__name__}")
        print(f"   Message: {str(e)}")
        print(f"\n{'=' * 60}")
        print("❌ Could not connect to Neo4j")
        print(f"{'=' * 60}")
        print(f"\n💡 Common fixes:")
        print(f"   1. Make sure Neo4j is running")
        print(f"   2. Check NEO4J_URI in .env file")
        print(f"   3. Verify NEO4J_USER and NEO4J_PASSWORD are correct")
        print(f"   4. Test connection: neo4j-admin server console (if installed locally)")
        print()
        return False

if __name__ == "__main__":
    sys.exit(0 if test_neo4j_connection() else 1)

