/**
 * 测试循环引用的 Shape
 * Node.next 引用另一个 Node
 */

function sumList(head) {
    let sum = 0;
    let current = head;
    while (current) {
        sum += current.value;
        current = current.next;  // next 是另一个 Node 的引用
    }
    return sum;
}

// 测试
let node3 = {value: 3, next: null};
let node2 = {value: 2, next: node3};
let node1 = {value: 1, next: node2};

console.log("Sum:", sumList(node1));  // 应该输出 6
