#!/usr/bin/env python3
"""
Quick script to check bot_logs in Firestore
"""
from google.cloud import firestore

# Initialize Firestore
db = firestore.Client(project='double-venture-442318-k8')

# Query bot_logs collection
logs_ref = db.collection('bot_logs')
query = logs_ref.order_by('sequence', direction=firestore.Query.DESCENDING).limit(20)

docs = list(query.stream())

print(f"📊 Found {len(docs)} log documents in Firestore")
print()

if docs:
    print("Recent logs:")
    print("-" * 80)
    for doc in docs:
        data = doc.to_dict()
        print(f"ID: {doc.id}")
        print(f"  Bot: {data.get('bot_id')}")
        print(f"  Run: {data.get('run_id')}")
        print(f"  Seq: {data.get('sequence')}")
        print(f"  Level: {data.get('level')}")
        print(f"  Time: {data.get('timestamp')}")
        print(f"  Message: {data.get('message', '')[:100]}...")
        print()
else:
    print("❌ No log documents found in bot_logs collection")
    print()
    
    # Check if collection exists at all
    collections = list(db.collections())
    print(f"Available collections: {[c.id for c in collections]}")
