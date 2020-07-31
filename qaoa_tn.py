from functools import reduce
import itertools
import networkx as nx
import numpy as np
import tensornetwork as tn

import tree_tools


def regular_prefix_tree(degree, depth):
    """Generates a regular prefix tree, that is, a prefix tree on the set of strings in
       {0, ..., degree - 1}^depth.
    
    Parameters
    ----------
    degree: int
        The degree of the tree (i.e. the number of incident vertices of an internal node).
    depth: int
        The depth of the tree.
    
    Returns
    -------
    tuple
        The first element of the tuple is the generated prefix tree (as a NetworkX directed graph),
        the second element is its root. Each node of the tree has a 'source' attribute: for the root,
        it is set to None, while for a depth-n node associated to the string x_1 ... x_n which is a
        descendant of a node x_1 ... x_{n - 1}, the 'source' attribute is set to x_n.
    """
    graph, root = nx.generators.trees.prefix_tree(itertools.product(*([tuple(range(degree))] + [tuple(range(degree - 1))] * (depth - 1))))
    to_remove = []
    for node in graph.nodes:
        if graph.nodes[node]["source"] == "NIL":
            to_remove.append(node)
    for node in to_remove:
        graph.remove_node(node)
    return graph, root

def edge_choices_to_node(tree, root, edge_choices):
    """Return the node corresponding to a string for a prefix tree generated by regular_prefix_tree()
    
    Parameters
    ----------
    tree: NetworkX directed graph
        The prefix tree.
    root: node
        The root of the prefix tree.
    edge_choices: list
        A list of integers specifying the string the wanted node corresponds to
    
    Returns
    -------
    node
        The node specifiying by the string in the prefix tree.
    """
    current_node = root
    #print("edge choices: {}".format(edge_choices))
    for edge_choice in edge_choices:
        #print("current_node: {}".format(current_node))
        successor_found = False
        for node in tree.successors(current_node):
            #print("successor {}'s source: {}".format(node, tree.nodes[node]["source"]))
            if tree.nodes[node]["source"] == edge_choice:
                current_node = node
                successor_found = True
                break
        if not successor_found:
            raise ValueError("invalid edge choice {}".format(edge_choice))
    return current_node

def ising_rotation_matrix(gamma, qubits, edges):
    """Produce an Ising rotation matrix, i.e. a product of unitaries of the form $\exp(-i\frac{\gamma}{2}Z_jZ_k)$,
       acting on specified qubits, along specified edges.
    
    Parameters
    ----------
    gamma: float
        The rotation angle.
    qubits: list
        The list of qubits on which the resulting unitary will act.
    edges: list
        The list of edges along which to apply Ising rotations, where each edge is given by a tuple.
        For each edge (j, k), there will be a multiplicative contribution $\exp(-i\frac{\gamma}{2}Z_jZ_k)$
        to the final unitary.
    
    Returns
    -------
    numpy array
        A matrix with 2 ** len(qubits) rows and columns which is the product of Ising rotations acting along
        each edge. The order of the Kronecker product is prescribed by the order in which the qubits involved
        are listed in the 'qubits' argument.
    """
    qubit_to_idx = {
        qubit: qubit_idx
        for qubit_idx, qubit in enumerate(qubits)
    }
    edges_idx = [
        (qubit_to_idx[qubit1], qubit_to_idx[qubit2])
        for qubit1, qubit2 in edges
    ]
    rotations = [
        reduce(
            np.kron,
            [
                np.cos(gamma / 2) * np.eye(2) if idx == qubit1_idx
                else np.eye(2)
                for idx in range(len(qubits))
            ]
        ) +
        reduce(
            np.kron,
            [
                -1j * np.sin(gamma / 2) * np.diag([1, -1]) if idx == qubit1_idx
                else np.diag([1, -1]) if idx == qubit2_idx
                else np.eye(2)
                for idx in range(len(qubits))
            ]
        )
        for qubit1_idx, qubit2_idx in edges_idx
    ]
    return reduce(lambda x, y: x @ y, rotations, reduce(np.kron, [np.eye(2)] * len(qubits)))

def tree_tensor_network_layer(
    beta,
    gamma,
    tree,
    tree_root,
    odd,
    initial_final=False,
    dag=False,
    extra_operators={}
):
    """Create tensors corresponding to one layer of QAOA Tree Tensor Network.
    
    Parameters
    ----------
    beta: float
        The $\beta$ parameter of the mixing unitaries.
    gamma: float
        The $\gamma$ parameter of the Ising rotations.
    tree: NetworkX digraph
        The underlying tree of the Tree Tensor Network.
    tree_root: node
        The root of the underlying tree of the Tree Tensor Network.
    odd: bool
        Whether the layer is an even or odd one (even and odd layers have a different structure).
    initial_final: bool
        Whether the layer is either an initial or final layer.
    dag: bool
        Whether the layer is a dagger layer (that is, a layer implement part of $U^{\dagger}$ if $U$ is the
        QAOA unitary).
    extra_operators: dict
        A dictionary specifying the single-qubit operators to insert between $U$ and $U^{\dagger}$ is $U$ is
        the unitary implementing QAOA. In a (key, value) pair, the key is a qubit and the value is a Numpy
        array representing the single-qubit operator acting on this qubit.
    
    Returns
    -------
    list
        A list of 3-tuples describing the TensorNetwork tensors constituting the layer. The elements of the
        3-tuples are the following:
            - A TensorNetwork tensor.
            - The node of the underlying tree on which this tensor is based.
            - The successors of this base node in the underyling tree.
    """
    tensors = []
    if dag:
        beta = -beta
        gamma = -gamma
    for depth in range(int(odd), tree_tools.tree_depth(tree, tree_root), 2):
        for root in nx.descendants_at_distance(tree, tree_root, depth):
            successors = list(tree.successors(root))
            ising_matrix = ising_rotation_matrix(gamma, [root] + successors, [(root, successor) for successor in successors])
            extra_operators_matrix_factors = []
            if odd:
                mixer_matrix_factors = [np.cos(beta / 2) * np.eye(2) - 1j * np.sin(beta / 2) * np.array([[0, 1], [1, 0]])] * (len(successors) + 1)
                extra_operators_matrix_factors = [extra_operators.get(node, np.eye(2)) for node in [root] + successors]
            elif root == tree_root:
                mixer_matrix_factors = [np.cos(beta / 2) * np.eye(2) - 1j * np.sin(beta / 2) * np.array([[0, 1], [1, 0]])] + [np.eye(2)] * len(successors)
                extra_operators_matrix_factors = [extra_operators.get(root, np.eye(2))] + [np.eye(2)] * len(successors)
            else:
                mixer_matrix_factors = [np.eye(2)] * (1 + len(successors))
                extra_operators_matrix_factors = [np.eye(2)] * (1 + len(successors))
            #print("qubits: {}".format([root] + successors, extra_operators_matrix_factors))
            #print("factors: {}".format(extra_operators_matrix_factors))
            mixer_matrix = reduce(np.kron, mixer_matrix_factors)
            extra_operators_matrix = reduce(np.kron, extra_operators_matrix_factors)
            if dag:
                matrix = ising_matrix @ mixer_matrix @ extra_operators_matrix
            else:
                matrix = extra_operators_matrix @ mixer_matrix @ ising_matrix
            if initial_final:
                if dag:
                    matrix = reduce(np.kron, [np.ones(2) / np.sqrt(2)] * (len(successors) + 1)).T @ matrix
                else:
                    matrix = matrix @ reduce(np.kron, [np.ones(2) / np.sqrt(2)] * (len(successors) + 1))
                tensor = tn.Node(matrix.reshape((2,) * (len(successors) + 1)))
                tensors.append((tensor, root, successors))
            else:
                tensor = tn.Node(matrix.reshape((2,) * 2 * (len(successors) + 1)))
                tensors.append((tensor, root, successors))
    return tensors

def qaoa_tensor_network(betas, gammas, tree, tree_root, extra_operators={}):
    """Create a QAOA Tree Tensor Network.
    
    Parameters
    ----------
    betas: list
        The $\beta$ parameters of the QAOA ansatz.
    gammas: list
        The $\gamma$ parameters of the QAOA ansatz.
    tree: NetworkX directed graph
        The underlying tree of the Tree Tensor Network.
    tree_root: node
        The root of the underlying tree of the Tree Tensor Network.
    extra_operators: dict
        A dictionary specifying the single-qubit operators to insert between $U$ and $U^{\dagger}$ is $U$ is
        the unitary implementing QAOA. In a (key, value) pair, the key is a qubit and the value is a Numpy
        array representing the single-qubit operator acting on this qubit.
    
    Returns
    -------
    dict
        A dictionary mapping each node of the underlying tree to the list of tensors based on this node.
    """
    tensors_by_root = {}
    def update_tensors_by_root(new_tensors_info):
        for new_tensor_info in new_tensors_info:
            root = new_tensor_info[1]
            if root not in tensors_by_root:
                tensors_by_root[root] = []
            tensors_by_root[root].append(new_tensor_info[0])
    # QAOA circuit
    for layer in range(len(betas)):
        tensors_even = tree_tensor_network_layer(
            beta=betas[layer],
            gamma=gammas[layer],
            tree=tree,
            tree_root=tree_root,
            odd=False,
            initial_final=(layer == 0),
            dag=False,
            extra_operators=(extra_operators if layer == len(betas) - 1 else {})
        )
        tensors_odd = tree_tensor_network_layer(
            beta=betas[layer],
            gamma=gammas[layer],
            tree=tree,
            tree_root=tree_root,
            odd=True,
            initial_final=False,
            dag=False,
            extra_operators=(extra_operators if layer == len(betas) - 1 else {})
        )
        update_tensors_by_root(tensors_even)
        update_tensors_by_root(tensors_odd)
    # QAOA dagger circuit
    for layer in range(len(betas) - 1, -1, -1):
        tensors_odd = tree_tensor_network_layer(
            beta=betas[layer],
            gamma=gammas[layer],
            tree=tree,
            tree_root=tree_root,
            odd=True,
            initial_final=False,
            dag=True
        )
        tensors_even = tree_tensor_network_layer(
            beta=betas[layer],
            gamma=gammas[layer],
            tree=tree,
            tree_root=tree_root,
            odd=False,
            initial_final=(layer == 0),
            dag=True
        )
        update_tensors_by_root(tensors_even)
        update_tensors_by_root(tensors_odd)
    return tensors_by_root

def contract_children(tree, tree_root, tensors_by_root, edge_choices):
    """Contract the children of a node in a QAOA Tree Tensor Network and return the vector resulting
       from the contraction.
       
    Parameters
    ----------
    tree: NetworkX directed graph
        The underlying tree of the Tree Tensor Network.
    tree_root: node
        The root of the underlying tree of the Tree Tensor Network.
    tensors_by_root: dict
        A dictionary mapping each node of the underlying tree to the list of tensors based on this node
        (see also qaoa_tensor_network()).
    edge_choices: list
        A sequence of integers specifying the node whose children to contract (see edge_choices_to_node()).
    
    Returns
    -------
    TensorNetwork tensor
        A tensor representing the value of the node specified by argument 'edge_choices' once its children
        have been contracted.
    """
    depth = tree_tools.tree_depth(tree, tree_root)
    root = edge_choices_to_node(tree, tree_root, edge_choices)
    #print("edge choices: {}".format(edge_choices))
    if len(edge_choices) > depth:
        raise ValueError("too high internal node depth: {} >= {}".format(len(edge_choices), depth))
    elif len(edge_choices) == 0:
        partial_contraction1 = contract_children(tree, tree_root, tensors_by_root, edge_choices + [0])
        partial_contraction2 = contract_children(tree, tree_root, tensors_by_root, edge_choices + [1])
        partial_contraction3 = contract_children(tree, tree_root, tensors_by_root, edge_choices + [2])
        tensors_copy = list(tn.copy(tensors_by_root[tree_root])[0].values())
        for i in range(len(tensors_copy) - 1):
            tensors_copy[int((i + 1) / 2)][5 if i % 2 else 1] ^ partial_contraction1[i]
            tensors_copy[-1 - int((i + 1) / 2)][1 if i % 2 or i == 0 else 5] ^ partial_contraction1[-1 - i]
            tensors_copy[int((i + 1) / 2)][6 if i % 2 else 2] ^ partial_contraction2[i]
            tensors_copy[-1 - int((i + 1) / 2)][2 if i % 2 or i == 0 else 6] ^ partial_contraction2[-1 - i]
            tensors_copy[int((i + 1) / 2)][7 if i % 2 else 3] ^ partial_contraction3[i]
            tensors_copy[-1 - int((i + 1) / 2)][3 if i % 2 or i == 0 else 7] ^ partial_contraction3[-1 - i]
        for i in range(len(tensors_copy) - 1):
            tensors_copy[i][0] ^ tensors_copy[i + 1][4 if i < len(tensors_copy) - 2 else 0]
        contraction = tn.contractors.greedy(
            tensors_copy + [partial_contraction1, partial_contraction2, partial_contraction3]
        )
        return contraction
    elif tree_tools.tree_depth(nx.dfs_tree(tree, root), root) == 0:
        num_tensors_per_stack = len(tn.copy(tensors_by_root[tree_root])[0].values())
        return tn.Node(np.eye(2 ** (num_tensors_per_stack - 1)).reshape((2,) * 2 * (num_tensors_per_stack - 1)))
        #return contraction
    else:
        partial_contraction1 = contract_children(tree, tree_root, tensors_by_root, edge_choices + [0])
        partial_contraction2 = contract_children(tree, tree_root, tensors_by_root, edge_choices + [1])
        tensors_copy = list(tn.copy(tensors_by_root[root])[0].values())
        if len(edge_choices) % 2:
            for i in range(len(tensors_copy) - 1):
                tensors_copy[int(i / 2)][1 if i % 2 else 4] ^ partial_contraction1[i]
                tensors_copy[-1 - int(i / 2)][4 if i % 2 else 1] ^ partial_contraction1[-1 - i]
                tensors_copy[int(i / 2)][2 if i % 2 else 5] ^ partial_contraction2[i]
                tensors_copy[-1 - int(i / 2)][5 if i % 2 else 2] ^ partial_contraction2[-1 - i]
            tensors_copy[int(len(tensors_copy) / 2) - 1][0] ^ tensors_copy[int(len(tensors_copy) / 2)][3]
            tensors_copy[int(len(tensors_copy) / 2) - 1][1] ^ tensors_copy[int(len(tensors_copy) / 2)][4]
            tensors_copy[int(len(tensors_copy) / 2) - 1][2] ^ tensors_copy[int(len(tensors_copy) / 2)][5]
            contraction = tn.contractors.greedy(
                tensors_copy + [partial_contraction1, partial_contraction2],
                output_edge_order=sum([
                    [tensors_copy[i][3], tensors_copy[i][0]]
                    for i in range(int(len(tensors_copy) / 2) - 1)
                ], []) + [
                    tensors_copy[int(len(tensors_copy) / 2) - 1][3],
                    tensors_copy[int(len(tensors_copy) / 2)][0]
                ] + sum([
                    [tensors_copy[i][3], tensors_copy[i][0]]
                    for i in range(int(len(tensors_copy) / 2) + 1, len(tensors_copy))
                ], [])
            )
        else:
            for i in range(len(tensors_copy) - 1):
                tensors_copy[int((i + 1) / 2)][4 if i % 2 else 1] ^ partial_contraction1[i]
                tensors_copy[-1 - int((i + 1) / 2)][1 if i % 2 or i == 0 else 4] ^ partial_contraction1[-1 - i]
                tensors_copy[int((i + 1) / 2)][5 if i % 2 else 2] ^ partial_contraction2[i]
                tensors_copy[-1 - int((i + 1) / 2)][2 if i % 2 or i == 0 else 5] ^ partial_contraction2[-1 - i]
            contraction = tn.contractors.greedy(
                tensors_copy + [partial_contraction1, partial_contraction2],
                output_edge_order=[
                    tensors_copy[0][0]
                ] + sum([
                    [tensors_copy[i][3], tensors_copy[i][0]]
                    for i in range(1, len(tensors_copy) - 1)
                ], []) + [
                    tensors_copy[-1][0]
                ]
            )
        return contraction