from google.cloud import firestore
 
class FirestoreDB:
    def __init__(self):
        self.db = firestore.Client()
 
    def add_document(self, collection_name, document_id, data):
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc_ref.set(data)
 
    def get_document(self, collection_name, document_id):
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc = doc_ref.get()
        if doc.exists:            
            return doc.to_dict()
        else:
            return None
 
    def update_document(self, collection_name, document_id, data):
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc_ref.update(data)
 
    def set_document(self, collection_name, document_id, data):
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc_ref.set(data)
        
 
    def delete_document(self, collection_name, document_id):
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc_ref.delete()
