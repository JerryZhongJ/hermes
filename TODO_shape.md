# Static Shape Speculative

这份计划目标是在static hermes上实现静态的投机优化，利用静态推测的object shape信息。

这意图带来两方面的性能提升：
1. 通过已知shape，来削弱属性访问指令的强度
2. 通过已知属性类型，来减少属性参与后续计算的强度。

## 前端

### 标注的格式

目前的标注只支持基本类型，参考`include/hermes/IRGen/TypeAnnotationLoader.h`。


## 中端
### ShapeGuard/ShapeAssert插入


### ShapeInference

这个pass类似于TypeInference，目的是判断LoadProperty/StoreProperty能够关联上哪些ShapeAssert，从而根据shape来优化LoadProperty/StoreProperty。

下面只讨论ShapeAssert。

#### 基本概念
- shape：对象的形状，包括每个属性的索引、名字以及类型。并且，这些属性是实际存储在对象中的，若不是通过getter、setter来访问、写入的。
- shape assertion: inst -> shape，表示assert这个指令的结果是满足shape的object。
    - TypeAssert本身asserted 指令。
    - 我们也会对一些phi设置assertion，为了方便算法实现。
- inherit assertion: 如果一个指令是Mov，而且操作数有assertion或者继承了assertion，那么这条指令继承了assertion。继承意味着一定被其主导。
- heap mutation：一个指令可能修改堆，从而破坏了assertion。
    - 实现上我们可以通过查看指令的SideEffect来判断，如果SideEffect包含WriteHeap或者ExecuteJS，则它是HeapMutation。
    - 对于LoadProperty，我们要分情况讨论：
        - 如果object操作数是NoShape、或者SingleShape：LoadProperty不会ExecuteJS（根据我们对Shape的要求），所以不是heap mutation。
        - object可能是any shapes：可能ExecuteJS，因此是heap mutation。
- valid assertion：一个assertion在一个程序点（指令）是valid的，如果从assertion到这个程序点的所有路径都不经过heap mutation。
- valid and dominent assertion：一个assertion在一个程序点是有效的，而且这个assertion能够主导这个程序点。
- 值的Shape状态：一个格结构，NoShape -> SingleShape -> AnyShapes
    - NoShape用于算法的初始状态，当算法遍历到一个值，它的状态就不会是NoShape
    - SingleShape要关联到一个具体的shape。
- SingleShape：一个值满足下面3个条件，否则就是AnyShapes。
    - 通过Mov或者Phi来源于asserted 的指令
    - 这些assertion有相同的shape
    - 这些assertion都是valid的

我们的目标就是判断哪些loadproperty/storeproperty的object操作数是SingleShape，因此将这些指令lower 成 prload/storeload。

#### 数据结构

这里是算法所需要的或者辅助的数据结构。

- mutationAfterLastAssert: set[Basic Block]。表示这个基本块内是否在最后一个asserted指令之后存在heap mutation。这个集合只进不出，因为：
    - 除了TypeAssert，新的assertion只会添加在phi，BB的开头。
    - Heap Mutation只会增加不会消失。其他指令是否是Heap Mutation是已知且固定的，只有LoadProperty可能变成Heap Mutation（从NoShape、SingleShape变成AnyShapes）。这个变化是单向的。
- mutationBefore: 
- assertion：inst -> shape。一个assertion可以由asserted inst表示，之后这两个名字是互换的。
- validDomAssertionAtEntry: BB -> Set[Inst]。在基本块的开头是有效且主导的assertion。如果缺失BB的记录，表示是全集。
- validDomAssertionAtExit：同上。
- inheritAssertionFrom：inst -> inst。表示一条指令继承了哪条指令的assertion。key一定是Mov指令。

#### 算法流程

1. 初始化
    - 找到所有TypeAssert，加入asertion中。
    - 在TypeAssert之后，看是否有heap mutation。如果有，把当前基本块加进mutationAfterLastAssert。
    - 入口基本块的validDomAssertionAtEntry为空集。
    - 其他的validDomAssertionAtEntry、validDomAssertionAtExit初始化为全集，不需要操作。
2. 迭代添加Phi assertion。
    1. 传播inheritAssertionFrom，对于一个assertion，将其Mov下游的inheritAssertionFrom设置为这个assertion。
    1. 遍历所有phi，给满足条件的phi添加assertion：
        - 所有incoming value都有assertion或者继承assertion
        - 这些assertion 都assert成同一个shape。
    3. 如果没有添加新的assertion，结束循环。否则，跳到1.

3. 迭代循环：
    2. 传播有效且主导assertion：
        - 块内传播：
            - 如果当前块BB属于mutationAfterLastAssert，那么validDomAssertionAtExit[BB] = {}
            - 如果不属于，遍历指令：初始validDomAssertionAtExit[BB]为validDomAssertionAtEntry[BB]的拷贝，遇到assertion，加进；遇到heap mutation，清空。
        - 块间传播：validDomAssertionAtEntry[BB]是所有前继validDomAssertionAtExit[BB']的交集。
        - 注意validDomAssertionAtEntry和validDomAssertionAtExit可能是全集的情况。
    3. 迭代撤销phi Assertion。
        1. 遍历所有phi，判断是否满足条件。不满足的撤销它的assertion
            - 所有incoming value都有assertion或者继承assertion
            - 这些assertion 都assert成同一个shape。
            - incoming value的assertion或者继承的assertion在各自的incoming block exit有效
        2. 对于撤销的assertion，更新其Mov下游的inheritAssertionFrom。
        3. 如果没有撤销的assertion，退出循环。如果有则继续。
    3. 更新loadproperty/storeproperty的shape状态：
          1. 如果object操作数有assertion或者继承assertion，该assertion在当前代码块入口有效，且当前指令前面没有heap mutation。则是SingleShape，否则是AnyShapes。
          2. 如果LoadProperty由NoShape、SingleShape变成AnyShapes，则该指令变成heap mutation。如果当前基本块不是mutationAfterLastAssert，查看该指令后有没有assertion，没有则把当前基本块放进mutationAfterLastAssert。
    4. 上述步骤如果某一步有更新，继续循环。否则，退出。
 4. loadproperty/storeproperty降级。遍历这两类指令，如果object操作数的shape状态是SingleShape，利用关联shape来降级为prload/prstore。

#### 迭代的单向性

- validdomAssertionAtEntry、validdomAssertionAtEntry从全集，每一步变成子集。
- phi：从asserted、变为不是asserted
- Shape状态：从NoShape -> SingleShape -> AnyShapes
###