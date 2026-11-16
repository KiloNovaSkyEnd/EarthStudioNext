"""Small node builder shared by native geostationary mapping and soft rim."""
class Nodes:
    def __init__(self, tree):
        self.tree = tree
        tree.nodes.clear()

    def node(self, kind):
        return self.tree.nodes.new(kind)

    def put(self, value, socket):
        if hasattr(value, 'node'):
            self.tree.links.new(value, socket)
        else:
            socket.default_value = value

    def m(self, operation, a, b=None):
        node = self.node('ShaderNodeMath')
        node.operation = operation
        self.put(a, node.inputs[0])
        if b is not None:
            self.put(b, node.inputs[1])
        return node.outputs[0]

    def v(self, operation, a, b=None):
        node = self.node('ShaderNodeVectorMath')
        node.operation = operation
        self.put(a, node.inputs[0])
        if b is not None:
            self.put(b, node.inputs['Scale'] if operation == 'SCALE' else node.inputs[1])
        return node.outputs['Value'] if operation in ('LENGTH', 'DOT_PRODUCT') else node.outputs['Vector']

    def xyz(self, vector):
        node = self.node('ShaderNodeSeparateXYZ')
        self.put(vector, node.inputs[0])
        return tuple(node.outputs)

    def combine(self, values):
        node = self.node('ShaderNodeCombineXYZ')
        for value, socket in zip(values, node.inputs):
            self.put(value, socket)
        return node.outputs[0]

    def prop(self, scene, name):
        node = self.node('ShaderNodeValue')
        node.label = name
        driver = node.outputs[0].driver_add('default_value').driver
        variable = driver.variables.new()
        variable.name = 'value'
        variable.targets[0].id_type = 'SCENE'
        variable.targets[0].id = scene
        variable.targets[0].data_path = '["'+name+'"]'
        driver.expression = 'value'
        return node.outputs[0]
