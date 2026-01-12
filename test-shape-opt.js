/**
 * 测试 Shape-Typed Optimization
 * 验证 LoadProperty 被优化为 PrLoad
 */

function distance(p) {
    // 这两个属性访问应该被优化为 PrLoad
    let x = p.x;
    let y = p.y;
    return Math.sqrt(x * x + y * y);
}

// 测试调用
let point = {x: 3, y: 4};
let dist = distance(point);
console.log("Distance:", dist); // 应该输出 5
