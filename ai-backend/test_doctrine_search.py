#!/usr/bin/env python3
"""
Test file to compare manual Cypher query results with AI Agent search flow.
Specifically tests the query: "Can you get all the doctrines from the database"

Usage: python test_doctrine_search.py
"""

import json
import sys
import os
from datetime import datetime
from typing import Dict, List, Any

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Look for .env in the current directory (ai-backend)
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(env_path)
    print(f"📄 Loaded environment variables from: {env_path}")
except ImportError:
    print("⚠️  python-dotenv not installed. Using system environment variables.")
except Exception as e:
    print(f"⚠️  Could not load .env file: {e}")

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

def test_manual_cypher_query():
    """Test the manual Cypher query to get all doctrines"""
    print("="*80)
    print(" MANUAL CYPHER QUERY TEST")
    print("="*80)
    
    manual_cypher = """
    MATCH (d:Doctrine)
    RETURN d.name as doctrine_name, 
           d.description as description,
           d.category as category,
           d.source as source,
           id(d) as doctrine_id,
           labels(d) as labels,
           properties(d) as all_properties
    ORDER BY d.name
    """
    
    print(f"Query: {manual_cypher.strip()}")
    
    try:
        from app.lib.neo4j_client import neo4j_client
        
        # Execute the manual query
        results = neo4j_client.execute_query(manual_cypher)
        
        print(f"\n✅ Manual query executed successfully")
        print(f"Results found: {len(results)}")
        
        # Display results
        if results:
            print(f"\n📋 DOCTRINE RESULTS ({len(results)} total):")
            for i, result in enumerate(results[:10]):  # Show first 10
                doctrine_name = result.get('doctrine_name', 'N/A')
                category = result.get('category', 'N/A')
                print(f"  {i+1:2d}. {doctrine_name}")
                if category != 'N/A':
                    print(f"      Category: {category}")
                if result.get('description'):
                    desc = result.get('description', '')[:100]
                    print(f"      Description: {desc}...")
                print()
            
            if len(results) > 10:
                print(f"  ... and {len(results) - 10} more doctrines")
        else:
            print("❌ No doctrines found in the database")
        
        return {
            'success': True,
            'cypher': manual_cypher.strip(),
            'results': results,
            'count': len(results)
        }
        
    except Exception as e:
        print(f"❌ Error executing manual query: {e}")
        return {
            'success': False,
            'cypher': manual_cypher.strip(),
            'results': [],
            'count': 0,
            'error': str(e)
        }

def test_ai_agent_search():
    """Test the AI Agent search flow"""
    print("\n" + "="*80)
    print(" AI AGENT SEARCH TEST")
    print("="*80)
    
    test_query = "Can you get all the doctrines from the database"
    print(f"Query: '{test_query}'")
    
    try:
        from app.routes.ai import search_with_crew, QueryRequest
        
        # Create request object
        request = QueryRequest(query=test_query)
        
        print("\n🤖 Executing AI Agent search...")
        
        # Execute the AI Agent search
        ai_result = search_with_crew(request)
        
        print(f"✅ AI search completed")
        print(f"Success: {ai_result.success}")
        print(f"Total results: {ai_result.total_results}")
        print(f"Execution time: {ai_result.execution_time:.2f}s" if ai_result.execution_time else "N/A")
        print(f"MCP tools used: {ai_result.mcp_tools_used}")
        
        # Display analysis
        if ai_result.analysis:
            print(f"\n📝 ANALYSIS SUMMARY:")
            print(f"Query interpretation: {ai_result.analysis.query_interpretation}")
            
            print(f"\n⚡ METHODOLOGY ({len(ai_result.analysis.methodology)} steps):")
            for i, step in enumerate(ai_result.analysis.methodology):
                print(f"  {i+1}. {step}")
            
            print(f"\n💡 KEY INSIGHTS ({len(ai_result.analysis.key_insights)}):")
            for i, insight in enumerate(ai_result.analysis.key_insights):
                print(f"  • {insight}")
            
            print(f"\n📋 FORMATTED RESULTS ({len(ai_result.analysis.formatted_results)}):")
            for i, result in enumerate(ai_result.analysis.formatted_results):
                print(f"  • {result}")
            
            if ai_result.analysis.raw_query_results:
                print(f"\n🔧 RAW QUERY RESULTS ({len(ai_result.analysis.raw_query_results)} items):")
                for i, result in enumerate(ai_result.analysis.raw_query_results[:5]):  # Show first 5
                    print(f"  {i+1}. {json.dumps(result, indent=4)}")
                if len(ai_result.analysis.raw_query_results) > 5:
                    print(f"  ... and {len(ai_result.analysis.raw_query_results) - 5} more items")
            
            if ai_result.analysis.limitations:
                print(f"\n⚠️  LIMITATIONS:")
                for limitation in ai_result.analysis.limitations:
                    print(f"  • {limitation}")
        
        return {
            'success': True,
            'ai_result': ai_result
        }
        
    except Exception as e:
        print(f"❌ Error executing AI search: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e)
        }

def compare_results(manual_result: Dict, ai_result: Dict):
    """Compare the results from manual query and AI search"""
    print("\n" + "="*80)
    print(" RESULTS COMPARISON")
    print("="*80)
    
    if not manual_result['success'] or not ai_result['success']:
        print("❌ Cannot compare - one or both queries failed")
        return
    
    manual_count = manual_result['count']
    ai_data = ai_result['ai_result']
    ai_count = len(ai_data.analysis.raw_query_results) if ai_data.analysis.raw_query_results else ai_data.total_results
    
    print(f"📊 RESULT COUNTS:")
    print(f"  Manual query: {manual_count} doctrines")
    print(f"  AI search: {ai_count} items")
    
    # Compare counts
    if manual_count == ai_count and manual_count > 0:
        print("✅ Result counts match perfectly!")
    elif manual_count > 0 and ai_count > 0:
        difference = abs(manual_count - ai_count)
        percentage = (difference / max(manual_count, ai_count)) * 100
        print(f"⚠️  Result counts differ by {difference} ({percentage:.1f}%)")
    else:
        print("❌ One or both queries returned no results")
    
    # Analyze AI search quality
    if ai_data.success:
        print(f"\n🎯 AI SEARCH QUALITY:")
        
        quality_indicators = []
        
        # Check if MCP tools were used
        if ai_data.mcp_tools_used:
            quality_indicators.append("✅ MCP tools used")
        else:
            quality_indicators.append("❌ MCP tools not used")
        
        # Check if methodology mentions doctrines
        methodology_text = " ".join(ai_data.analysis.methodology).lower()
        if 'doctrine' in methodology_text:
            quality_indicators.append("✅ Methodology mentions doctrines")
        else:
            quality_indicators.append("❌ Methodology doesn't mention doctrines")
        
        # Check if formatted results contain doctrine information
        formatted_text = " ".join(ai_data.analysis.formatted_results).lower()
        if 'doctrine' in formatted_text:
            quality_indicators.append("✅ Formatted results contain doctrine info")
        else:
            quality_indicators.append("❌ Formatted results lack doctrine info")
        
        # Check if raw results are available
        if ai_data.analysis.raw_query_results:
            quality_indicators.append(f"✅ Raw query results available ({len(ai_data.analysis.raw_query_results)} items)")
        else:
            quality_indicators.append("❌ No raw query results")
        
        # Check query interpretation
        if 'doctrine' in ai_data.analysis.query_interpretation.lower():
            quality_indicators.append("✅ Query interpretation mentions doctrines")
        else:
            quality_indicators.append("❌ Query interpretation doesn't mention doctrines")
        
        for indicator in quality_indicators:
            print(f"  {indicator}")
        
        # Calculate quality score
        positive_count = sum(1 for indicator in quality_indicators if indicator.startswith("✅"))
        quality_score = positive_count / len(quality_indicators)
        
        print(f"\n📈 Quality Score: {positive_count}/{len(quality_indicators)} ({quality_score:.1%})")
        
        if quality_score >= 0.8:
            print("🏆 Excellent AI search performance!")
        elif quality_score >= 0.6:
            print("👍 Good AI search performance")
        elif quality_score >= 0.4:
            print("⚠️  Fair AI search performance - needs improvement")
        else:
            print("❌ Poor AI search performance - requires investigation")

def save_test_results(manual_result: Dict, ai_result: Dict):
    """Save test results to a JSON file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"doctrine_search_test_{timestamp}.json"
    
    test_data = {
        'test_info': {
            'query': "Can you get all the doctrines from the database",
            'timestamp': timestamp,
            'test_type': 'doctrine_search_comparison'
        },
        'manual_query': manual_result,
        'ai_search': {}
    }
    
    # Convert AI result to JSON-serializable format
    if ai_result['success']:
        ai_data = ai_result['ai_result']
        test_data['ai_search'] = {
            'success': ai_data.success,
            'query': ai_data.query,
            'total_results': ai_data.total_results,
            'execution_time': ai_data.execution_time,
            'mcp_tools_used': ai_data.mcp_tools_used,
            'cypher_queries': ai_data.cypher_queries,
            'analysis': {
                'query_interpretation': ai_data.analysis.query_interpretation,
                'methodology': ai_data.analysis.methodology,
                'key_insights': ai_data.analysis.key_insights,
                'patterns_identified': ai_data.analysis.patterns_identified,
                'limitations': ai_data.analysis.limitations,
                'formatted_results': ai_data.analysis.formatted_results,
                'raw_query_results': ai_data.analysis.raw_query_results
            }
        }
    else:
        test_data['ai_search'] = ai_result
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(test_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n💾 Test results saved to: {filename}")
    except Exception as e:
        print(f"❌ Error saving test results: {e}")

def main():
    """Main function to run the doctrine search test"""
    print("🧪 DOCTRINE SEARCH COMPARISON TEST")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check environment variables first
    print("\n🔧 Environment Configuration:")
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USER")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    
    print(f"NEO4J_URI: {neo4j_uri if neo4j_uri else '❌ Not set'}")
    print(f"NEO4J_USER: {neo4j_user if neo4j_user else '❌ Not set'}")
    print(f"NEO4J_PASSWORD: {'✅ Set' if neo4j_password else '❌ Not set'}")
    
    if not all([neo4j_uri, neo4j_user, neo4j_password]):
        print("\n❌ Missing required environment variables!")
        print("Please ensure the following environment variables are set:")
        print("- NEO4J_URI (your AuraDB connection string)")
        print("- NEO4J_USER (your AuraDB username)")
        print("- NEO4J_PASSWORD (your AuraDB password)")
        print("\nYou can set them in your shell or create a .env file.")
        return
    
    # Test Neo4j connection
    try:
        from app.lib.neo4j_client import neo4j_client
        print(f"\n🔗 Connecting to: {neo4j_uri}")
        test_result = neo4j_client.execute_query("MATCH (n) RETURN count(n) as total_nodes LIMIT 1")
        total_nodes = test_result[0]['total_nodes'] if test_result else 0
        print(f"✅ Neo4j connection successful. Total nodes in database: {total_nodes}")
    except Exception as e:
        print(f"❌ Neo4j connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Verify your AuraDB instance is running")
        print("2. Check your connection string (NEO4J_URI)")
        print("3. Verify your credentials (NEO4J_USER, NEO4J_PASSWORD)")
        print("4. Ensure your IP is whitelisted in AuraDB")
        return
    
    # Run tests
    try:
        # Step 1: Manual Cypher query
        manual_result = test_manual_cypher_query()
        
        # Step 2: AI Agent search
        ai_result = test_ai_agent_search()
        
        # Step 3: Compare results
        compare_results(manual_result, ai_result)
        
        # Step 4: Save results
        save_test_results(manual_result, ai_result)
        
        print("\n" + "="*80)
        print(" TEST COMPLETED SUCCESSFULLY! ✅")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 