from mongo_client import AtlasClient
from bson.objectid import ObjectId
# get all the users, and check if their available_courses list contains the id of the course
course_id = ObjectId("67e19ffd5c3291223a66475e")
users = [
"66aa9eafd221d572880a58a1",
"66fef6557bb8ff6c240cc0fe",
"670836b8ed741f5a0dff949f",
"672945fdc06e2d87f49c880c",
"67a7871d212a56c932cf3af2",
"67a78732212a56c932cf3b1a",
"67a78739212a56c932cf3b32",
"66aa9f63d221d572880a58b8",
"67d9a78d34eb5ea4af5181ee",
"67d9e5ed34eb5ea4af518c1c",
]

# add the above course to all the user's available courses
client = AtlasClient()
for user_id in users:
    user = client.find("users", {"_id": ObjectId(user_id)})[0]
    if course_id not in user["available_courses"]:
        user["available_courses"].append(course_id)
        client.update("users", {"_id": ObjectId(user["_id"])}, {
            "$set": {
                "available_courses": user["available_courses"]
            }
        })

print("Done")