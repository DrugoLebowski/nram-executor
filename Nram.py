import numpy as np
import NRamContext

from theano.tensor.nnet import relu, softmax, sigmoid

class NRam(object):

    def __init__(self, context: NRamContext) -> None:
        self.context = context

    def execute(self):
        in_mem, out_mem, regs = self.context.generate_mems()
        print("• Starting execution")

        # Iterate over sample
        for s in range(self.context.batch_size):
            print("• Initial memory: %s, Desired memory: %s, Initial registers: %s"
                  % (in_mem[s, :].argmax(axis=1), out_mem[s], regs[s, :].argmax(axis=1)))

            # Iterate for every timestep
            for t in range(self.context.timesteps):
                coeffs, _ = self.run_network(regs[s])

                regs[s], in_mem[s] = self.run_circuit(regs[s], in_mem[s], self.context.gates, coeffs)
                if t == self.context.timesteps - 1:
                    print("• (T = %d) Final memory: %s, desired memory: %s, final registers: %s\n\n"
                          % (t + 1, in_mem[s, :].argmax(axis=1), out_mem[s],regs[s, :].argmax(axis=1)))
                else:
                    print("• (T = %d) Memory : %s, registers: %s"
                          % (t + 1, in_mem[s, :].argmax(axis=1), regs[s, :].argmax(axis=1)))


    def avg(self, regs, coeff):
        return np.array(
            np.tensordot(
                regs.transpose([1, 0]), coeff.transpose([1, 0]), axes=1
            ).transpose([1, 0]),
            dtype=np.float32)

    def run_gate(self, gate_inputs, mem, gate, controller_coefficients):
        """Return the output of a gate in the circuit.

        gate_inputs:
          The values of the registers and previous gate outputs.
        gate:
          The gate to compute output for. Arity must
          match len(controller_coefficients).
        controller_coeffficients:
          A list of coefficient arrays from the controller,
          one coefficient for every gate input (0 for constants).
        """
        args = [self.avg(gate_inputs, coefficients)
                for coefficients in controller_coefficients]
        mem, output = gate(mem, *args)

        # Special-case constant gates.
        # Since they have no outputs, they always output
        # one sample. Repeat their outputs as many times
        # as necessary, effectively doing manual broadcasting
        # to generate an output of the right size.
        if gate.arity == 0:
            output = output[None, ...]

        return output, mem, args

    def run_circuit(self, registers, mem, gates, controller_coefficients):
        # Initially, only the registers may be used as inputs.
        gate_inputs = registers

        # Run through all the gates.
        for i, (gate, coeffs) in enumerate(zip(gates, controller_coefficients)):
            output, mem, args = self.run_gate(gate_inputs, mem, gate, coeffs)

            # Append the output of the gate as an input for future gates.
            gate_inputs = np.concatenate([gate_inputs, output])

        # All leftover coefficients are for registers.
        print(gate_inputs[np.arange(self.context.num_regs)])
        for i, coeff in enumerate(controller_coefficients[len(gates):]):
            gate_inputs[i] = self.avg(gate_inputs, coeff)

        print(gate_inputs[np.arange(self.context.num_regs)])
        return gate_inputs[np.arange(self.context.num_regs)], mem

    def run_network(self, registers: np.array) -> np.array:

        def take_params(values, i):
            """Return the next pair of weights and biases after the
            starting index and the new starting index."""
            return values[i], values[i + 1], i + 2

        # Extract the 0th (i.e. P( x = 0 )) component from all registers.
        last_layer = np.array(registers[:, 0][None, ...], dtype=np.float32)

        # Propogate forward to hidden layers.
        idx = 0
        for i in range(self.context.num_hidden_layers):
            W, b, idx = take_params(self.context.network, idx)
            last_layer = np.array(relu(last_layer.dot(W) + b), dtype=np.float32)

        controller_coefficients = []
        for i, gate in enumerate(self.context.gates):
            coeffs = []
            for j in range(gate.arity):
                W, b, idx = take_params(self.context.network, idx)
                layer = np.array(softmax(last_layer.dot(W) + b).eval(), dtype=np.float32)
                coeffs.append(layer)
            controller_coefficients.append(coeffs)

        # Forward propogate to new register value coefficients.
        for i in range(self.context.num_regs):
            W, b, idx = take_params(self.context.network, idx)
            coeffs = np.array(softmax(last_layer.dot(W) + b).eval(), dtype=np.float32)
            controller_coefficients.append(coeffs)

        # Forward propogate to generate willingness to complete.
        W, b, idx = take_params(self.context.network, idx)
        complete = np.array(sigmoid(last_layer.dot(W) + b).eval(), dtype=np.float32)

        return controller_coefficients, complete
