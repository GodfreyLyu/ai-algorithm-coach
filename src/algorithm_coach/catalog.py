"""Provide a small metadata-only catalog for local training and synthetic examples.

Tags are curated training labels. No problem statements or paid content are stored.
"""

CATALOG_VERSION = "1"

PROBLEMS = [
    {"id": "leetcode:1", "title": "Two Sum", "difficulty": "easy", "tags": ["array", "hash-table"], "url": "https://leetcode.com/problems/two-sum/"},
    {"id": "leetcode:20", "title": "Valid Parentheses", "difficulty": "easy", "tags": ["stack", "string"], "url": "https://leetcode.com/problems/valid-parentheses/"},
    {"id": "leetcode:21", "title": "Merge Two Sorted Lists", "difficulty": "easy", "tags": ["linked-list"], "url": "https://leetcode.com/problems/merge-two-sorted-lists/"},
    {"id": "leetcode:26", "title": "Remove Duplicates from Sorted Array", "difficulty": "easy", "tags": ["array", "two-pointers"], "url": "https://leetcode.com/problems/remove-duplicates-from-sorted-array/"},
    {"id": "leetcode:35", "title": "Search Insert Position", "difficulty": "easy", "tags": ["array", "binary-search"], "url": "https://leetcode.com/problems/search-insert-position/"},
    {"id": "leetcode:53", "title": "Maximum Subarray", "difficulty": "medium", "tags": ["array", "dynamic-programming"], "url": "https://leetcode.com/problems/maximum-subarray/"},
    {"id": "leetcode:70", "title": "Climbing Stairs", "difficulty": "easy", "tags": ["dynamic-programming"], "url": "https://leetcode.com/problems/climbing-stairs/"},
    {"id": "leetcode:94", "title": "Binary Tree Inorder Traversal", "difficulty": "easy", "tags": ["tree", "depth-first-search"], "url": "https://leetcode.com/problems/binary-tree-inorder-traversal/"},
    {"id": "leetcode:104", "title": "Maximum Depth of Binary Tree", "difficulty": "easy", "tags": ["tree", "depth-first-search"], "url": "https://leetcode.com/problems/maximum-depth-of-binary-tree/"},
    {"id": "leetcode:121", "title": "Best Time to Buy and Sell Stock", "difficulty": "easy", "tags": ["array"], "url": "https://leetcode.com/problems/best-time-to-buy-and-sell-stock/"},
    {"id": "leetcode:125", "title": "Valid Palindrome", "difficulty": "easy", "tags": ["two-pointers", "string"], "url": "https://leetcode.com/problems/valid-palindrome/"},
    {"id": "leetcode:141", "title": "Linked List Cycle", "difficulty": "easy", "tags": ["linked-list", "two-pointers"], "url": "https://leetcode.com/problems/linked-list-cycle/"},
    {"id": "leetcode:198", "title": "House Robber", "difficulty": "medium", "tags": ["dynamic-programming"], "url": "https://leetcode.com/problems/house-robber/"},
    {"id": "leetcode:200", "title": "Number of Islands", "difficulty": "medium", "tags": ["graph", "depth-first-search"], "url": "https://leetcode.com/problems/number-of-islands/"},
    {"id": "leetcode:206", "title": "Reverse Linked List", "difficulty": "easy", "tags": ["linked-list"], "url": "https://leetcode.com/problems/reverse-linked-list/"},
    {"id": "leetcode:217", "title": "Contains Duplicate", "difficulty": "easy", "tags": ["array", "hash-table"], "url": "https://leetcode.com/problems/contains-duplicate/"},
    {"id": "leetcode:226", "title": "Invert Binary Tree", "difficulty": "easy", "tags": ["tree", "depth-first-search"], "url": "https://leetcode.com/problems/invert-binary-tree/"},
    {"id": "leetcode:242", "title": "Valid Anagram", "difficulty": "easy", "tags": ["hash-table", "string"], "url": "https://leetcode.com/problems/valid-anagram/"},
    {"id": "leetcode:283", "title": "Move Zeroes", "difficulty": "easy", "tags": ["array", "two-pointers"], "url": "https://leetcode.com/problems/move-zeroes/"},
    {"id": "leetcode:704", "title": "Binary Search", "difficulty": "easy", "tags": ["array", "binary-search"], "url": "https://leetcode.com/problems/binary-search/"},
    {"id": "leetcode:733", "title": "Flood Fill", "difficulty": "easy", "tags": ["graph", "depth-first-search"], "url": "https://leetcode.com/problems/flood-fill/"},
    {"id": "leetcode:739", "title": "Daily Temperatures", "difficulty": "medium", "tags": ["stack"], "url": "https://leetcode.com/problems/daily-temperatures/"},
    {"id": "leetcode:977", "title": "Squares of a Sorted Array", "difficulty": "easy", "tags": ["array", "two-pointers"], "url": "https://leetcode.com/problems/squares-of-a-sorted-array/"},
    {"id": "leetcode:994", "title": "Rotting Oranges", "difficulty": "medium", "tags": ["graph", "breadth-first-search"], "url": "https://leetcode.com/problems/rotting-oranges/"},
]
