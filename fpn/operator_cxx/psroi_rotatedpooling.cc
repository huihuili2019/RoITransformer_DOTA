/*!
 * Copyright (c) 2017 by Contributors
 * Copyright (c) 2017 Microsoft
 * Licensed under The Apache-2.0 License [see LICENSE for details]
 * \file psroi_pooling.cc
 * \brief psroi pooling operator
 * \author Yi Li, Tairui Chen, Guodong Zhang, Haozhi Qi, Jifeng Dai
 * modified by Jian Ding
*/
#include "./psroi_rotatedpooling-inl.h"
#include <mshadow/base.h>
#include <mshadow/tensor.h>
#include <mshadow/packet-inl.h>
#include <mshadow/dot_engine-inl.h>
#include <cassert>

using std::max;
using std::min;
using std::floor;
using std::ceil;

namespace mshadow {
template<typename DType>
inline void PSROIROTATEDPoolForward(const Tensor<cpu, 4, DType> &out,
                           const Tensor<cpu, 4, DType> &data,
                           const Tensor<cpu, 2, DType> &bbox,
                           const float spatial_scale_,
                           const int output_dim_,
                           const int group_size_) {
  // NOT_IMPLEMENTED;
  return;
}

template<typename DType>
inline void PSROIROTATEDPoolBackwardAcc(const Tensor<cpu, 4, DType> &in_grad,
                            const Tensor<cpu, 4, DType> &out_grad,
                            const Tensor<cpu, 2, DType> &bbox,
                            const float spatial_scale_,
                            const int output_dim_,
                            const int group_size_) {
  // NOT_IMPLEMENTED;
  return;
}
}  // namespace mshadow

namespace mxnet {
namespace op {

template<>
Operator *CreateOp<cpu>(PSROIROTATEDPoolingParam param, int dtype) {
  Operator* op = NULL;
  MSHADOW_REAL_TYPE_SWITCH(dtype, DType, {
    op = new PSROIROTATEDPoolingOp<cpu, DType>(param);
  });
  return op;
}

Operator *PSROIROTATEDPoolingProp::CreateOperatorEx(Context ctx, std::vector<TShape> *in_shape,
                                           std::vector<int> *in_type) const {
  std::vector<TShape> out_shape, aux_shape;
  std::vector<int> out_type, aux_type;
  CHECK(InferType(in_type, &out_type, &aux_type));
  CHECK(InferShape(in_shape, &out_shape, &aux_shape));
  DO_BIND_DISPATCH(CreateOp, param_, in_type->at(0));
}

DMLC_REGISTER_PARAMETER(PSROIROTATEDPoolingParam);

MXNET_REGISTER_OP_PROPERTY(_contrib_PSROIROTATEDPooling, PSROIROTATEDPoolingProp)
.describe("Performs region-of-interest pooling on inputs. Resize bounding box coordinates by "
"spatial_scale and crop input feature maps accordingly. The cropped feature maps are pooled "
"by max pooling to a fixed size output indicated by pooled_size. batch_size will change to "
"the number of region bounding boxes after PSROIROTATEDPooling")
.add_argument("data", "Symbol", "Input data to the pooling operator, a 4D Feature maps")
.add_argument("rois", "Symbol", "Bounding box coordinates, a 2D array of "
"[[batch_index, x_ctr, y_ctr, w, h, theta]]. "
"of designated region of interest. batch_index indicates the index of corresponding image "
"in the input data")
.add_arguments(PSROIROTATEDPoolingParam::__FIELDS__());
}  // namespace op
}  // namespace mxnet
