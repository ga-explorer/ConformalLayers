from .utils import DenseTensor, ScalarTensor, SizeAny
from abc import abstractmethod
from collections import OrderedDict
from typing import Optional, Tuple, Union
import MinkowskiEngine as me
import torch


ForwardMinkowskiData = Tuple[me.SparseTensor, ScalarTensor]               # (X, alpha_upper), where X is the canonical representation of the input including all coordinates, and alpha_upper is the upper limit for hypersphere radius
ForwardTorchData = Tuple[Tuple[DenseTensor, ScalarTensor], ScalarTensor]  # ((Xe, Xw), alpha_upper), where Xe includes the Euclidean coordinates of the input, Xw is the homogeneous coordinate of the input, and alpha_upper is the upper limit for hypersphere radius


class ConformalModule(torch.nn.Module):
    def __init__(self,
                 *, name: Optional[str]=None) -> None:
        super(ConformalModule, self).__init__()
        self._name = name
    
    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({", ".join(map(lambda pair: "{}={}".format(*pair), self._repr_dict().items()))})'

    def _repr_dict(self) -> OrderedDict:
        entries = OrderedDict()
        if self._name is not None:
            entries['name'] = self.name
        return entries

    def forward(self, input: Union[ForwardMinkowskiData, ForwardTorchData]) -> Union[ForwardMinkowskiData, ForwardTorchData]:
        raise NotImplementedError # This method must be implementd by the subclasses

    @abstractmethod
    def output_dims(self, *in_size: int) -> SizeAny:
        pass

    @property
    @abstractmethod
    def minkowski_module(self) -> torch.nn.Module:
        pass

    @property
    def name(self) -> Optional[str]:
        return self._name

    @property
    @abstractmethod
    def torch_module(self) -> torch.nn.Module:
        pass


class WrappedMinkowskiStridedOperation(torch.nn.Module):
    def __init__(self,
                 owner: ConformalModule,
                 transposed: bool) -> None:
        super(WrappedMinkowskiStridedOperation, self).__init__()
        # Declare basic properties
        self._owner = (owner,) # We use a tuple to avoid infinite recursion while PyTorch traverses the module's tree
        self._transposed = transposed
        self._kernel_generator = me.KernelGenerator(kernel_size=owner.kernel_size, stride=1, dilation=owner.dilation, dimension=len(owner.kernel_size))
        # Compute some constant values and keep them
        kernel_origin = owner.dilation * ((owner.kernel_size - 1) // 2) * (owner.kernel_size % 2)
        dilated_kernel_size = owner.dilation * (owner.kernel_size - 1) + 1
        self._kernel_start_offset = kernel_origin - dilated_kernel_size + 1
        self._kernel_end_offset = kernel_origin
        self._index_start_offset = kernel_origin - owner.padding
        self._index_end_offset = kernel_origin + owner.padding - dilated_kernel_size + 2

    @abstractmethod
    def _apply_function(self, input: me.SparseTensor, alpha_upper: ScalarTensor, region_type: me.RegionType, region_offset: torch.IntTensor, out_coords_key: me.CoordsKey) -> Tuple[DenseTensor, ScalarTensor]:
        pass

    def forward(self, input: ForwardMinkowskiData) -> ForwardMinkowskiData:
        input, alpha_upper = input
        in_coords = input.coords
        indices_per_batch = input.decomposed_coordinates
        # Compute the complete set of coordinates for evaluating the module
        index_start = self._index_start_offset
        index_end = in_coords[:, 1:].max(0)[0] + self._index_end_offset #TODO How to replace the max function call by some predefined value?
        out_coords = torch.cat(tuple(torch.stack(torch.meshgrid(torch.as_tensor((batch,), dtype=torch.int32, device=in_coords.device), *map(lambda start, end, step: torch.arange(int(start), int(end), int(step), dtype=torch.int32, device=in_coords.device),
            torch.max(index_start, ((indices.min(0)[0] + self._kernel_start_offset - index_start) // self.owner.stride) * self.owner.stride + index_start),
            torch.min(index_end, ((indices.max(0)[0] + self._kernel_end_offset - index_start) // self.owner.stride + 1) * self.owner.stride + index_start),
            self.owner.stride)), dim=-1).view(-1, 1 + input.dimension) for batch, indices in enumerate(indices_per_batch)), dim=0)
        #TODO assert (torch.abs(output.feats) <= 1e-6).all(), 'Os limites do arange(...) precisam ser ajustados, pois coordenadas irrelevantes são geradas em casos a serem investigados
        # Create a region_type, region_offset, and coords_key
        region_type, region_offset, _ = self._kernel_generator.get_kernel(input.tensor_stride, self._transposed)
        out_coords_key = input.coords_man.create_coords_key(out_coords, tensor_stride=1, force_creation=True, force_remap=True, allow_duplicate_coords=True)
        # Evaluate the module
        out_feats, alpha_upper = self._apply_function(input, alpha_upper, region_type, region_offset, out_coords_key)
        # Map the first indices to zeros and compress the resulting coordinates when needed
        if (index_start != 0).any():
            out_coords[:, 1:] -= index_start
            if (self.owner.stride != 1).any():
                out_coords[:, 1:] //= self.owner.stride
            output = me.SparseTensor(out_feats, out_coords, coords_manager=input.coords_man, force_creation=True)
        elif (self.owner.stride != 1).any():
            out_coords[:, 1:] //= self.owner.stride
            output = me.SparseTensor(out_feats, out_coords, coords_manager=input.coords_man, force_creation=True)
        else:
            output = me.SparseTensor(out_feats, coords_key=out_coords_key, coords_manager=input.coords_man)
        return output, alpha_upper

    @property
    def owner(self) -> ConformalModule:
        return self._owner[0]

    @property
    def transposed(self) -> bool:
        return self._transposed

    @property
    def kernel_generator(self) -> me.KernelGenerator:
        return self._kernel_generator
